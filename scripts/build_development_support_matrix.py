#!/usr/bin/env python3
"""Build a conservative support-matrix draft for a development EVM host.

The existing Celer matrix predates the multi-host replay receipt and remains
validated by its historical script.  This companion command applies the same
fail-closed rules to the other source-backed development hosts so every replay
receipt can bind to a host-specific matrix.  It never upgrades a draft to an
admission decision: unobserved features remain ``unknown`` and every report
requires owner acceptance and differential evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossllm.contracts.canonical import sha256_hex
from crossllm.replay import EVMExecutionSupportMatrix, SupportEntry, SupportStatus
from dataset.tools import extract_all_artifacts
from scripts import build_evm_support_matrix as celer_matrix


LINEAGES = ("chainbridge", "layerzero_v2")
LINEAGE_CONFIG: dict[str, dict[str, str]] = {
    "chainbridge": {
        "contract": "Bridge",
        "source": "contracts/Bridge.sol",
        "matrix_id": "chainbridge-foundry-development-v1",
    },
    "layerzero_v2": {
        "contract": "SendUln302",
        "source": "contracts/EndpointV2.sol",
        # The LayerZero artifact pack is centered on SendUln302, while the
        # paired harness executes EndpointV2.  Bind this host matrix to the
        # checked-in Foundry output for the actual harness target instead of
        # silently pairing unrelated source and bytecode identities.
        "bytecode": "out/EndpointV2.sol/EndpointV2.json",
        "matrix_id": "layerzero-v2-foundry-development-v1",
    },
}
# ChainBridge uses the public artifact-pack bytecode; LayerZero uses the
# checked-in Foundry output for the actual paired-harness target.
LINEAGE_CONFIG["chainbridge"]["bytecode"] = "bytecode/Bridge.deployed.hex"
DEFAULT_OUTPUT = {
    lineage: ROOT / "dataset" / "reports" / f"evm_support_matrix_{lineage}.json"
    for lineage in LINEAGES
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _entry(
    category: str,
    feature: str,
    status: SupportStatus,
    *,
    evidence_hash: str,
    condition: str | None = None,
    note: str | None = None,
) -> SupportEntry:
    return SupportEntry(
        category=category,
        feature=feature,
        status=status,
        condition=condition,
        evidence_hash=evidence_hash,
        note=note,
    )


def _matrix_inputs(root: Path, lineage: str) -> tuple[Path, Path, Path, Path, dict[str, Any]]:
    config = LINEAGE_CONFIG.get(lineage)
    if config is None:
        raise ValueError(f"unsupported non-Celer development lineage: {lineage}")
    harness_root = root / "dataset" / "harness" / lineage
    artifact_root = root / "dataset" / "artifacts" / lineage
    bytecode_descriptor = Path(config.get("bytecode", ""))
    if lineage == "chainbridge":
        bytecode_path = artifact_root / bytecode_descriptor
    else:
        bytecode_path = harness_root / bytecode_descriptor
    source_path = harness_root / config["source"]
    manifest_path = harness_root / "source_manifest.json"
    profile_path = artifact_root / "channel_profile.json"
    for path in (bytecode_path, source_path, manifest_path, profile_path):
        if not path.is_file():
            raise ValueError(f"{lineage}: missing support-matrix input: {path}")
    return bytecode_path, source_path, manifest_path, profile_path, config


def _bytecode_hex(path: Path) -> str:
    """Read deployed bytecode from either a hex fixture or Foundry JSON."""

    if path.suffix.lower() != ".json":
        value = path.read_text(encoding="utf-8").strip()
    else:
        payload = _load_object(path)
        deployed = payload.get("deployedBytecode")
        if not isinstance(deployed, dict) or not isinstance(deployed.get("object"), str):
            raise ValueError(f"{path}: Foundry artifact has no deployedBytecode.object")
        value = deployed["object"]
    if not value.startswith("0x"):
        raise ValueError(f"{path}: deployed bytecode must start with 0x")
    return value


def _disassemble_opcode_names(path: Path) -> tuple[str, ...]:
    """Disassemble the same opcode scope as the original Celer matrix."""

    raw = bytes.fromhex(_bytecode_hex(path)[2:])
    used: set[str] = set()
    index = 0
    while index < len(raw):
        opcode = raw[index]
        used.add(celer_matrix._OPCODE_NAMES.get(opcode, f"0x{opcode:02x}"))
        index += 1
        if 0x60 <= opcode <= 0x7F:
            index += opcode - 0x5F
    return tuple(sorted(used))


def build_matrix(
    root: Path = ROOT,
    lineage: str = "chainbridge",
) -> tuple[EVMExecutionSupportMatrix, dict[str, Any]]:
    """Build one hash-bound, draft-only support matrix."""

    root = root.resolve()
    bytecode_path, source_path, manifest_path, profile_path, config = _matrix_inputs(root, lineage)
    artifact_root = root / "dataset" / "artifacts" / lineage
    manifest = _load_object(manifest_path)
    deployment = _load_object(artifact_root / "deployment.json")
    source_hash = sha256_file(source_path)
    bytecode_hash = sha256_file(bytecode_path)
    artifact_hash = sha256_file(artifact_root / "manifest.json")
    profile_hash = sha256_file(profile_path)
    manifest_hash = sha256_file(manifest_path)
    used_opcodes = _disassemble_opcode_names(bytecode_path)
    used_set = set(used_opcodes)

    opcode_scope = (
        "CALLER", "CALLVALUE", "CALLDATASIZE", "CALLDATACOPY", "EXTCODEHASH",
        "RETURNDATASIZE", "RETURNDATACOPY", "CHAINID", "TIMESTAMP", "SELFBALANCE",
        "SHA3", "SLOAD", "SSTORE", "CALL", "DELEGATECALL", "STATICCALL",
        "CREATE", "CREATE2", "SELFDESTRUCT", "PUSH0",
    )
    entries: list[SupportEntry] = []
    for opcode in opcode_scope:
        if opcode in used_set:
            entries.append(_entry(
                "opcode", opcode, SupportStatus.SUPPORTED,
                evidence_hash=bytecode_hash,
                note="opcode is present in the locked deployed bytecode; native Foundry replay executes the host artifact",
            ))
        else:
            entries.append(_entry(
                "opcode", opcode, SupportStatus.UNKNOWN,
                evidence_hash=bytecode_hash,
                note="not observed in the locked deployed bytecode; no support claim is admitted without a dedicated probe",
            ))

    selected_contracts = deployment.get("contracts")
    if not isinstance(selected_contracts, dict) or not selected_contracts:
        raise ValueError(f"{lineage}: deployment has no selected contracts")
    is_proxy = any(
        isinstance(value, dict)
        and isinstance(value.get("proxy"), dict)
        and value["proxy"].get("is_proxy") is True
        for value in selected_contracts.values()
    )
    if is_proxy:
        entries.append(_entry(
            "proxy", "none", SupportStatus.UNKNOWN,
            evidence_hash=artifact_hash,
            note="selected deployment contains a proxy; implementation and initialization must be resolved before replay support can be claimed",
        ))
    else:
        entries.append(_entry(
            "proxy", "none", SupportStatus.SUPPORTED,
            evidence_hash=artifact_hash,
            note="deployment metadata declares all selected targets non-proxy with no initializer",
        ))
    entries.extend((
        _entry("proxy", "eip1967", SupportStatus.CONDITIONAL, evidence_hash=artifact_hash,
               condition="implementation bytecode, slot and initialization configuration must be pinned"),
        _entry("proxy", "transparent", SupportStatus.CONDITIONAL, evidence_hash=artifact_hash,
               condition="implementation/admin/configuration hashes must be pinned"),
        _entry("proxy", "beacon", SupportStatus.CONDITIONAL, evidence_hash=artifact_hash,
               condition="beacon and resolved implementation hashes must be pinned"),
        _entry("proxy", "diamond", SupportStatus.CONDITIONAL, evidence_hash=artifact_hash,
               condition="facet table and selector map must be pinned"),
    ))

    for precompile in (
        "ecrecover@0x01", "sha256@0x02", "ripemd160@0x03", "identity@0x04",
        "modexp@0x05", "bn128_add@0x06", "bn128_mul@0x07",
        "bn128_pairing@0x08", "blake2f@0x09", "point_evaluation@0x0a",
    ):
        entries.append(_entry(
            "precompile", precompile, SupportStatus.UNKNOWN,
            evidence_hash=bytecode_hash,
            note=f"no precompile call site is admitted by the {lineage} development source/bytecode probe",
        ))

    source_text = source_path.read_text(encoding="utf-8")
    uses_keccak = "keccak256" in source_text or "keccak" in source_text.lower()
    entries.extend((
        _entry(
            "crypto", "keccak256",
            SupportStatus.SUPPORTED if uses_keccak else SupportStatus.UNKNOWN,
            evidence_hash=source_hash,
            note=(
                f"source-level message/accounting derivations in the locked {lineage} source use keccak256"
                if uses_keccak
                else f"keccak256 was not observed in the locked {lineage} source; no host support claim"
            ),
        ),
        _entry("crypto", "ecdsa_recover", SupportStatus.UNKNOWN, evidence_hash=source_hash,
               note=f"not independently probed for the locked {lineage} source"),
        _entry("crypto", "sha256", SupportStatus.UNKNOWN, evidence_hash=source_hash,
               note=f"not independently probed for the locked {lineage} source"),
        _entry("crypto", "ripemd160", SupportStatus.UNKNOWN, evidence_hash=source_hash,
               note=f"not independently probed for the locked {lineage} source"),
    ))

    matrix = EVMExecutionSupportMatrix(
        matrix_id=config["matrix_id"],
        engine="foundry-evm",
        engine_revision=extract_all_artifacts.DOCKER_FOUNDRY,
        entries=tuple(entries),
        acceptance_status="draft",
    )
    scan = {
        "bytecode_path": str(bytecode_path.relative_to(root)).replace("\\", "/"),
        "bytecode_sha256": bytecode_hash,
        "unique_opcodes": list(used_opcodes),
        "scan_hash": sha256_hex({"bytecode_sha256": bytecode_hash, "unique_opcodes": list(used_opcodes)}),
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "evm_execution_support_matrix",
        "scope": "source_backed_development_host_draft",
        "lineage_id": lineage,
        "source_repository": manifest.get("source_repository"),
        "source_commit": manifest.get("source_commit"),
        "source_manifest_sha256": manifest_hash,
        "source_file_sha256": source_hash,
        "artifact_manifest_sha256": artifact_hash,
        "profile_sha256": profile_hash,
        "matrix": matrix.as_dict(),
        "bytecode_opcode_scan": scan,
        "source_backed": True,
        "acceptance_status": "draft",
        "acceptance_owner": None,
        "accepted_at": None,
        "acceptance_agent": None,
        "independent_validation_required": False,
        "independent_differential_required": True,
        "admission_eligible": False,
        "evidence_scope": "source_backed_development_host_draft",
    }
    report["report_hash"] = sha256_hex(report)
    return matrix, report


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_report(
    root: Path = ROOT,
    lineage: str = "chainbridge",
    report_path: Path | None = None,
) -> list[str]:
    root = root.resolve()
    path = report_path or DEFAULT_OUTPUT.get(lineage, root / "dataset" / "reports" / f"evm_support_matrix_{lineage}.json")
    try:
        report = _load_object(path)
        matrix, expected = build_matrix(root, lineage)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"support matrix report unreadable: {error}"]
    errors: list[str] = []
    body = dict(report)
    stored_hash = body.pop("report_hash", None)
    if stored_hash != sha256_hex(body):
        errors.append("support matrix report hash mismatch")
    for key in (
        "schema_version", "record_type", "scope", "lineage_id", "source_repository",
        "source_commit", "source_manifest_sha256", "source_file_sha256",
        "artifact_manifest_sha256", "profile_sha256", "source_backed", "acceptance_status",
        "acceptance_owner", "accepted_at", "acceptance_agent", "independent_validation_required",
        "independent_differential_required", "admission_eligible",
        "evidence_scope", "bytecode_opcode_scan",
    ):
        if report.get(key) != expected.get(key):
            errors.append(f"{key} mismatch")
    actual_matrix = report.get("matrix")
    if not isinstance(actual_matrix, dict):
        return errors + ["matrix object is missing"]
    try:
        decoded = EVMExecutionSupportMatrix.from_dict(actual_matrix)
    except ValueError as error:
        return errors + [f"matrix invalid: {error}"]
    if decoded.as_dict() != actual_matrix:
        errors.append("matrix is not canonical")
    if decoded.matrix_hash != matrix.matrix_hash:
        errors.append("matrix content does not match locked inputs")
    if actual_matrix.get("acceptance_status") != "draft":
        errors.append("development support matrix must remain draft")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--lineage", choices=LINEAGES, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.out.resolve() if args.out else DEFAULT_OUTPUT[args.lineage]
    try:
        if args.check:
            errors = validate_report(root, args.lineage, output)
            if errors:
                print("FAILED")
                print("\n".join(errors))
                return 1
            print(f"OK: {args.lineage} EVM support matrix is valid and remains draft/non-admission")
            return 0
        _, report = build_matrix(root, args.lineage)
        _atomic_json(output, report)
        print(f"support matrix written to: {output}")
        print(f"matrix_hash: {report['matrix']['matrix_hash']}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
