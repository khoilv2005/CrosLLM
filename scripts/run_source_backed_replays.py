#!/usr/bin/env python3
"""Run hash-bound Foundry replays for all source-backed development hosts.

This is a concrete native-EVM replay boundary, not an evaluation oracle.  The
receipt records the locked source/artifact/deployment/profile/compiler and the
host support-matrix identities for Celer, ChainBridge and LayerZero v2.  The
report deliberately keeps independent evaluator/property/trigger flags false;
those require separate evidence before evaluation admission.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossllm.contracts import ReplayStatus
from crossllm.contracts.canonical import sha256_hex
from crossllm.replay import FoundryDockerReplay, FoundryReplaySpec
from dataset.tools import extract_all_artifacts
from scripts import build_development_support_matrix
from scripts import build_evm_support_matrix


LINEAGES = ("celer_cbridge", "chainbridge", "layerzero_v2")
DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "source_backed_replays.json"
FOUNDRY_IMAGE = extract_all_artifacts.DOCKER_FOUNDRY
PRIMARY_SOURCE = {
    "celer_cbridge": "contracts/CBridge.sol",
    "chainbridge": "contracts/Bridge.sol",
    # The paired LayerZero harness executes the protocol EndpointV2 source;
    # SendUln302 is the separate artifact-pack selection and is not silently
    # presented as the replayed contract.
    "layerzero_v2": "contracts/EndpointV2.sol",
}
MATRIX_PATH = {
    "celer_cbridge": Path("dataset/reports/evm_support_matrix_celer_cbridge.json"),
    "chainbridge": Path("dataset/reports/evm_support_matrix_chainbridge.json"),
    "layerzero_v2": Path("dataset/reports/evm_support_matrix_layerzero_v2.json"),
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _matrix(root: Path, lineage: str) -> tuple[Any, dict[str, Any]]:
    if lineage == "celer_cbridge":
        return build_evm_support_matrix.build_matrix(root)
    return build_development_support_matrix.build_matrix(root, lineage)


def _matrix_validation_errors(root: Path, lineage: str) -> list[str]:
    matrix_path = root / MATRIX_PATH[lineage]
    if lineage == "celer_cbridge":
        return build_evm_support_matrix.validate_report(root, matrix_path)
    return build_development_support_matrix.validate_report(root, lineage, matrix_path)


def _source_file(root: Path, lineage: str) -> Path:
    path = root / "dataset" / "harness" / lineage / PRIMARY_SOURCE[lineage]
    if not path.is_file():
        raise ValueError(f"{lineage}: primary source file is missing: {path}")
    return path


def build_replay_spec(root: Path, lineage: str, compiler_volume: str) -> FoundryReplaySpec:
    if lineage not in LINEAGES:
        raise ValueError(f"unsupported source-backed development lineage: {lineage}")
    root = root.resolve()
    harness_root = root / "dataset" / "harness" / lineage
    artifact_root = root / "dataset" / "artifacts" / lineage
    if not harness_root.is_dir() or not artifact_root.is_dir():
        raise ValueError(f"{lineage}: source-backed harness or artifact pack is missing")
    manifest = _load_object(harness_root / "source_manifest.json")
    config = _load_object(harness_root / "harness_config.json")
    if manifest.get("lineage_id") != lineage or config.get("source_commit") != manifest.get("source_commit"):
        raise ValueError(f"{lineage}: source-backed manifest/config identity mismatch")
    matrix, _ = _matrix(root, lineage)
    matrix_path = root / MATRIX_PATH[lineage]
    if not matrix_path.is_file() or _matrix_validation_errors(root, lineage):
        raise ValueError(f"{lineage}: support matrix report is missing or invalid")
    compiler = config.get("compiler")
    if not isinstance(compiler, dict) or not isinstance(compiler.get("version"), str):
        raise ValueError(f"{lineage}: harness compiler identity is missing")
    compiler_version = compiler["version"]
    return FoundryReplaySpec(
        image_ref=FOUNDRY_IMAGE,
        project_path=harness_root,
        tool_revision="foundry-1.8.1",
        artifact_hash=sha256_file(artifact_root / "manifest.json"),
        initialization_hash=sha256_file(artifact_root / "deployment.json"),
        profile_hash=sha256_file(artifact_root / "channel_profile.json"),
        semantic_engine="independent-foundry-evm",
        compiler_version=compiler_version,
        test_filter=None,
        network_mode="none",
        timeout_seconds=300.0,
        compiler_volume=compiler_volume,
        compiler_image_ref=extract_all_artifacts.solc_image_for_version(compiler_version),
        support_matrix_hash=matrix.matrix_hash,
    )


def build_receipt(
    root: Path,
    lineage: str,
    spec: FoundryReplaySpec,
    result: Any,
    compiler: dict[str, str],
    *,
    observed_at: str,
) -> dict[str, Any]:
    root = root.resolve()
    harness_root = root / "dataset" / "harness" / lineage
    artifact_root = root / "dataset" / "artifacts" / lineage
    manifest = _load_object(harness_root / "source_manifest.json")
    source_path = _source_file(root, lineage)
    body: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "source_backed_independent_evm_replay",
        "scope": "source_backed_development_replay_only",
        "lineage_id": lineage,
        "source_repository": manifest.get("source_repository"),
        "source_commit": manifest.get("source_commit"),
        "source_manifest_sha256": sha256_file(harness_root / "source_manifest.json"),
        "source_file_sha256": sha256_file(source_path),
        "artifact_manifest_sha256": sha256_file(artifact_root / "manifest.json"),
        "initialization_sha256": sha256_file(artifact_root / "deployment.json"),
        "profile_sha256": sha256_file(artifact_root / "channel_profile.json"),
        "replay_spec": spec.as_dict(),
        "result": result.as_dict(),
        "compiler": compiler,
        "source_backed": True,
        "native_evm_replay": True,
        "independent_evaluator": False,
        "independent_property_validation": False,
        "independent_trigger_validation": False,
        "admission_eligible": False,
        "network_mode": "none",
        "evidence_scope": "source_backed_development_replay_only",
        "observed_at": observed_at,
    }
    body["receipt_hash"] = sha256_hex(body)
    return body


def _check_receipt(root: Path, receipt: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    lineage = receipt.get("lineage_id")
    if lineage not in LINEAGES:
        return [f"unknown replay lineage: {lineage}"]
    harness_root = root / "dataset" / "harness" / lineage
    artifact_root = root / "dataset" / "artifacts" / lineage
    try:
        manifest = _load_object(harness_root / "source_manifest.json")
        source_path = _source_file(root, lineage)
        expected_scalars = {
            "schema_version": 1,
            "record_type": "source_backed_independent_evm_replay",
            "scope": "source_backed_development_replay_only",
            "lineage_id": lineage,
            "source_repository": manifest.get("source_repository"),
            "source_commit": manifest.get("source_commit"),
            "source_manifest_sha256": sha256_file(harness_root / "source_manifest.json"),
            "source_file_sha256": sha256_file(source_path),
            "artifact_manifest_sha256": sha256_file(artifact_root / "manifest.json"),
            "initialization_sha256": sha256_file(artifact_root / "deployment.json"),
            "profile_sha256": sha256_file(artifact_root / "channel_profile.json"),
            "source_backed": True,
            "native_evm_replay": True,
            "independent_evaluator": False,
            "independent_property_validation": False,
            "independent_trigger_validation": False,
            "admission_eligible": False,
            "network_mode": "none",
            "evidence_scope": "source_backed_development_replay_only",
        }
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"{lineage}: replay identity unreadable: {error}"]
    for key, expected in expected_scalars.items():
        if receipt.get(key) != expected:
            errors.append(f"{lineage}: {key} mismatch")

    body = dict(receipt)
    stored_hash = body.pop("receipt_hash", None)
    if stored_hash != sha256_hex(body):
        errors.append(f"{lineage}: receipt hash mismatch")

    spec_data = receipt.get("replay_spec")
    result_data = receipt.get("result")
    compiler = receipt.get("compiler")
    if not isinstance(spec_data, dict) or not isinstance(result_data, dict) or not isinstance(compiler, dict):
        return errors + [f"{lineage}: replay spec, result or compiler identity is missing"]
    try:
        spec = FoundryReplaySpec(
            image_ref=spec_data["image_ref"],
            project_path=Path(spec_data["project_path"]),
            tool_revision=spec_data["tool_revision"],
            artifact_hash=spec_data["artifact_hash"],
            initialization_hash=spec_data["initialization_hash"],
            profile_hash=spec_data["profile_hash"],
            semantic_engine=spec_data["semantic_engine"],
            compiler_version=spec_data.get("compiler_version"),
            test_filter=spec_data.get("test_filter"),
            network_mode=spec_data["network_mode"],
            timeout_seconds=float(spec_data["timeout_seconds"]),
            support_matrix_hash=spec_data.get("support_matrix_hash"),
            compiler_volume=spec_data.get("compiler_volume"),
            compiler_image_ref=spec_data.get("compiler_image_ref"),
        )
    except (KeyError, TypeError, ValueError) as error:
        return errors + [f"{lineage}: replay spec invalid: {error}"]
    if spec.as_dict() != spec_data:
        errors.append(f"{lineage}: replay spec hash or fields are not canonical")
    if spec.project_path != harness_root.resolve():
        errors.append(f"{lineage}: replay project is not the locked harness")
    try:
        matrix, _ = _matrix(root, lineage)
        if spec.support_matrix_hash != matrix.matrix_hash:
            errors.append(f"{lineage}: replay spec is not bound to the current support matrix")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"{lineage}: support matrix identity unavailable: {error}")
    if result_data.get("spec_hash") != spec.spec_hash:
        errors.append(f"{lineage}: replay result/spec hash mismatch")
    if result_data.get("status") != ReplayStatus.PASS.value:
        errors.append(f"{lineage}: replay did not pass")
    if result_data.get("exit_code") != 0:
        errors.append(f"{lineage}: replay exit code is not zero")
    if not isinstance(result_data.get("test_count"), int) or result_data["test_count"] <= 0:
        errors.append(f"{lineage}: replay has no test count")
    if result_data.get("passed_tests") != result_data.get("test_count") or result_data.get("failed_tests") != 0:
        errors.append(f"{lineage}: replay test counts are not all passing")
    compiler_version = spec.compiler_version
    if compiler.get("version") != compiler_version or compiler.get("image") != spec.compiler_image_ref:
        errors.append(f"{lineage}: compiler identity does not match replay spec")
    if compiler.get("path") != "/compiler/solc" or not isinstance(compiler.get("binary_sha256"), str):
        errors.append(f"{lineage}: compiler binary identity is incomplete")
    return errors


def validate_report(root: Path = ROOT, report_path: Path = DEFAULT_OUTPUT) -> list[str]:
    root = root.resolve()
    path = report_path.resolve()
    try:
        report = _load_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"source-backed replays report unreadable: {error}"]
    errors: list[str] = []
    body = dict(report)
    stored_hash = body.pop("report_hash", None)
    if stored_hash != sha256_hex(body):
        errors.append("source-backed replays report hash mismatch")
    for key, expected in {
        "schema_version": 1,
        "record_type": "source_backed_independent_evm_replays",
        "scope": "source_backed_development_replay_only",
        "source_backed": True,
        "native_evm_replay": True,
        "independent_evaluator": False,
        "independent_property_validation": False,
        "independent_trigger_validation": False,
        "admission_eligible": False,
        "network_mode": "none",
        "evidence_scope": "source_backed_development_replay_only",
    }.items():
        if report.get(key) != expected:
            errors.append(f"{key} mismatch")
    receipts = report.get("receipts")
    if not isinstance(receipts, list):
        return errors + ["receipts must be a list"]
    by_lineage = {row.get("lineage_id"): row for row in receipts if isinstance(row, dict)}
    if set(by_lineage) != set(LINEAGES) or len(receipts) != len(LINEAGES):
        errors.append(f"replay lineage coverage mismatch: expected {list(LINEAGES)}")
    for lineage in LINEAGES:
        receipt = by_lineage.get(lineage)
        if receipt is None:
            continue
        errors.extend(_check_receipt(root, receipt))
    return errors


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(root: Path = ROOT, output: Path = DEFAULT_OUTPUT) -> int:
    root = root.resolve()
    observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    receipts: list[dict[str, Any]] = []
    for lineage in LINEAGES:
        volume = extract_all_artifacts.create_compiler_cache_volume(f"source-replay-{lineage}")
        try:
            compiler = extract_all_artifacts.populate_compiler_cache_volume(
                volume,
                _load_object(root / "dataset" / "harness" / lineage / "harness_config.json")["compiler"]["version"],
            )
            spec = build_replay_spec(root, lineage, volume)
            result = FoundryDockerReplay().run(spec)
            print(f"{lineage}: {result.passed_tests}/{result.test_count} pass ({result.status.value})")
            if result.status is not ReplayStatus.PASS:
                print(f"{lineage}: replay failed: {result.reason}")
                return 1
            receipts.append(build_receipt(root, lineage, spec, result, compiler, observed_at=observed_at))
        finally:
            extract_all_artifacts.remove_compiler_cache_volume(volume)
    report: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "source_backed_independent_evm_replays",
        "scope": "source_backed_development_replay_only",
        "receipts": receipts,
        "source_backed": True,
        "native_evm_replay": True,
        "independent_evaluator": False,
        "independent_property_validation": False,
        "independent_trigger_validation": False,
        "admission_eligible": False,
        "network_mode": "none",
        "evidence_scope": "source_backed_development_replay_only",
        "observed_at": observed_at,
    }
    report["report_hash"] = sha256_hex(report)
    _atomic_json(output.resolve(), report)
    print(f"source-backed replay report written to: {output.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.out.resolve() if args.out else DEFAULT_OUTPUT
    try:
        if args.check:
            errors = validate_report(root, output)
            if errors:
                print("FAILED")
                print("\n".join(errors))
                return 1
            print("OK: all source-backed development EVM replays are valid and non-admission")
            return 0
        return run(root, output)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
