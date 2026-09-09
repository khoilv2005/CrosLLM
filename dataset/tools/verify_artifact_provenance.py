#!/usr/bin/env python3
"""Verify contract-level provenance for extracted development artifact packs.

This is a diagnostic gate, not an admission writer.  It compares the current
pack with the locked source checkout and requires the extractor's explicit
source/ABI/bytecode/storage/deployment hashes.  A non-empty bytecode file or a
matching Git commit alone is never sufficient.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataset.tools.extract_all_artifacts import (  # noqa: E402
    LINEAGE_SPECS,
    _canonical_hash,
    _contract_declared_name,
    _file_hash,
    _resolve_contract_source,
    dependency_closure,
    deterministic_source_selection,
    stable_abi_symbols,
    source_target_metadata,
)


DEV_LINEAGES = ("hop", "layerzero_v2", "celer_cbridge", "chainbridge")


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_lineage(root: Path, source_cache: Path, lineage_id: str) -> dict[str, object]:
    spec = LINEAGE_SPECS.get(lineage_id)
    if spec is None:
        return {"lineage_id": lineage_id, "status": "FAIL", "errors": ["lineage is not registered"]}
    artifact_root = root / "dataset" / "artifacts" / lineage_id
    source_root = source_cache / lineage_id
    errors: list[str] = []
    try:
        symbols = _load(artifact_root / "symbols.json")
        deployment = _load(artifact_root / "deployment.json")
        build_info = _load(artifact_root / "build_info.json")
        receipt = _load(artifact_root / "source_receipt.json")
    except (OSError, json.JSONDecodeError, TypeError) as error:
        return {"lineage_id": lineage_id, "status": "FAIL", "errors": [f"metadata unreadable: {error}"]}

    lock = _load(root / "dataset" / "sources" / "source_lock.json")
    lock_row = next(
        (row for row in lock.get("lineages", []) if isinstance(row, dict) and row.get("lineage_id") == lineage_id),
        None,
    ) if isinstance(lock, dict) else None
    if not isinstance(lock_row, dict):
        errors.append("source lock row is missing")
    else:
        if receipt.get("source_commit") != lock_row.get("commit"):
            errors.append("source receipt commit does not match source lock")
        if receipt.get("source_repo") != spec.get("source_repo"):
            errors.append("source receipt repository does not match extractor spec")

    if not source_root.is_dir():
        errors.append(f"source cache is missing: {source_root}")

    symbol_contracts = symbols.get("contracts") if isinstance(symbols, dict) else None
    deployment_contracts = deployment.get("contracts") if isinstance(deployment, dict) else None
    settings = build_info.get("compiler_settings") if isinstance(build_info, dict) else None
    if not isinstance(symbol_contracts, dict):
        errors.append("symbols.json has no contracts object")
        symbol_contracts = {}
    if not isinstance(deployment_contracts, dict):
        errors.append("deployment.json has no contracts object")
        deployment_contracts = {}
    if not isinstance(settings, dict):
        errors.append("build_info.json is missing compiler_settings")
    elif build_info.get("compiler_settings_sha256") != _canonical_hash(settings):
        errors.append("compiler_settings_sha256 mismatch")
    recorded_dependencies = build_info.get("dependency_closure") if isinstance(build_info, dict) else None
    if recorded_dependencies is not None and source_root.is_dir():
        try:
            actual_dependencies = dependency_closure(source_root)
        except (OSError, RuntimeError) as error:
            errors.append(f"dependency closure hash failed: {error}")
        else:
            if recorded_dependencies != actual_dependencies:
                errors.append("dependency_closure mismatch")
    recorded_stable_symbols = symbols.get("stable_symbols") if isinstance(symbols, dict) else None
    if isinstance(recorded_stable_symbols, list):
        if symbols.get("stable_symbols_sha256") != _canonical_hash(recorded_stable_symbols):
            errors.append("stable_symbols_sha256 mismatch")
    recorded_domains = symbols.get("domain_assignments") if isinstance(symbols, dict) else None
    expected_domains = spec.get("contract_domains")
    if recorded_domains != expected_domains:
        errors.append("domain_assignments do not match the locked contract domains")
    expected_stable_symbols: list[dict[str, object]] = []
    selection_path = artifact_root / "selection.json"
    if selection_path.is_file() and source_root.is_dir():
        try:
            recorded_selection = _load(selection_path)
            actual_selection = deterministic_source_selection(
                source_root, str(spec.get("subpath", "")), spec["contracts"]
            )
        except (OSError, RuntimeError, ValueError) as error:
            errors.append(f"source selection verification failed: {error}")
        else:
            if recorded_selection != actual_selection:
                errors.append("source selection mismatch")

    for contract_name, target in spec["contracts"].items():
        symbol = symbol_contracts.get(contract_name)
        deployed = deployment_contracts.get(contract_name)
        if not isinstance(symbol, dict):
            errors.append(f"{contract_name}: symbols provenance is missing")
            continue
        if not isinstance(deployed, dict):
            errors.append(f"{contract_name}: deployment provenance is missing")
            continue
        if source_root.is_dir():
            try:
                source_file = _resolve_contract_source(source_root, str(spec.get("subpath", "")), target)
                source_hash = _file_hash(source_file)
                if symbol.get("source_file_sha256") != source_hash:
                    errors.append(f"{contract_name}: source_file_sha256 mismatch")
                try:
                    actual_target = source_target_metadata(
                        source_file, _contract_declared_name(target)
                    )
                except RuntimeError as error:
                    errors.append(f"{contract_name}: source target metadata failed: {error}")
                else:
                    if actual_target.get("deployable_source_target") is not True:
                        errors.append(
                            f"{contract_name}: selected source target is not deployable "
                            f"({actual_target.get('kind')})"
                        )
                    recorded_targets = [
                        symbol.get("source_target"),
                        deployed.get("source_target"),
                    ]
                    if any(recorded != actual_target for recorded in recorded_targets):
                        errors.append(f"{contract_name}: source_target metadata mismatch")
            except (OSError, RuntimeError) as error:
                errors.append(f"{contract_name}: source hash failed: {error}")
        try:
            abi_path = deployed.get("abi_path")
            storage_path = deployed.get("storage_layout_path")
            if not isinstance(abi_path, str) or not isinstance(storage_path, str):
                raise ValueError("ABI/storage paths are missing")
            abi = _load(artifact_root / abi_path)
            storage_layout = _load(artifact_root / storage_path)
            if not isinstance(abi, list) or not isinstance(storage_layout, dict):
                raise ValueError("ABI must be an array and storage layout must be an object")
            source_path = symbol.get("source_path")
            if not isinstance(source_path, str) or not source_path:
                source_path = str(Path(str(spec.get("subpath", ""))) / target.partition(":")[0]).replace("\\", "/")
            source_hash_for_symbols = symbol.get("source_file_sha256")
            if not isinstance(source_hash_for_symbols, str) or not source_hash_for_symbols:
                raise ValueError("source_file_sha256 is missing")
            expected_stable_symbols.extend(
                stable_abi_symbols(
                    contract_name,
                    source_path,
                    source_hash_for_symbols,
                    abi,
                    storage_layout,
                    str(expected_domains[contract_name]),
                )
            )
        except (OSError, RuntimeError, ValueError, TypeError) as error:
            errors.append(f"{contract_name}: stable symbol recomputation failed: {error}")
        for field, artifact_key in (
            ("abi_sha256", "abi_path"),
            ("creation_bytecode_sha256", "creation_bytecode_path"),
            ("deployed_bytecode_sha256", "deployed_bytecode_path"),
            ("storage_layout_sha256", "storage_layout_path"),
        ):
            relative = deployed.get(artifact_key)
            expected = deployed.get(field)
            if not isinstance(relative, str) or not isinstance(expected, str):
                errors.append(f"{contract_name}: missing {artifact_key}/{field}")
                continue
            path = artifact_root / relative
            try:
                actual = _file_hash(path)
            except RuntimeError as error:
                errors.append(f"{contract_name}: {error}")
                continue
            if actual != expected:
                errors.append(f"{contract_name}: {field} mismatch")
            if symbol.get(field) is not None and symbol.get(field) != expected:
                errors.append(f"{contract_name}: symbols and deployment {field} disagree")
        if deployed.get("constructor_args_sha256") != _canonical_hash(deployed.get("constructor_args")):
            errors.append(f"{contract_name}: constructor_args_sha256 mismatch")
        initializer_args = deployed.get("initializer_args")
        if initializer_args is None:
            initializer_args = []
        if deployed.get("initializer_args_sha256") != _canonical_hash(initializer_args):
            errors.append(f"{contract_name}: initializer_args_sha256 mismatch")

    expected_stable_symbols.sort(key=lambda item: str(item["symbol_id"]))
    if isinstance(recorded_stable_symbols, list) and recorded_stable_symbols != expected_stable_symbols:
        errors.append("stable_symbols do not match ABI/storage artifacts and explicit domains")

    return {
        "lineage_id": lineage_id,
        "status": "PASS" if not errors else "FAIL",
        "artifact_root": str(artifact_root),
        "source_root": str(source_root),
        "errors": errors,
    }


def verify(
    root: Path = ROOT,
    source_cache: Path | None = None,
    lineages: tuple[str, ...] = DEV_LINEAGES,
) -> dict[str, object]:
    resolved_root = Path(root).resolve()
    cache = Path(source_cache).resolve() if source_cache is not None else resolved_root.parent / "crossllm_private_sources"
    rows = [_verify_lineage(resolved_root, cache, lineage) for lineage in lineages]
    return {
        "schema_version": 1,
        "status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL",
        "lineages": rows,
        "admission_note": "diagnostic provenance verification only; no admission status is changed",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source-cache", type=Path, default=None)
    parser.add_argument("--lineage", action="append", dest="lineages", choices=sorted(LINEAGE_SPECS))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    report = verify(
        args.root,
        args.source_cache,
        tuple(args.lineages) if args.lineages else DEV_LINEAGES,
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
