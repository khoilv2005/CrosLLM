#!/usr/bin/env python3
"""Build and validate the host-specific EVM support matrix for Celer.

The matrix is deliberately conservative.  A feature observed in the locked
deployed bytecode/source is marked supported for the Foundry host used by the
development replay.  Features not observed are kept unknown (or conditional
when the condition is explicit), so absence of a probe is never reported as
support.  The result is development evidence only until the project owner
accepts the matrix and a differential evaluator is attached.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import hashlib
import json
import os
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossllm.contracts.canonical import sha256_hex
from crossllm.replay import EVMExecutionSupportMatrix, SupportEntry, SupportStatus
from dataset.tools import extract_all_artifacts


LINEAGE_ID = "celer_cbridge"
DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "evm_support_matrix_celer_cbridge.json"
ARTIFACT_REL = Path("dataset") / "artifacts" / LINEAGE_ID
HARNESS_REL = Path("dataset") / "harness" / LINEAGE_ID


_OPCODE_NAMES: dict[int, str] = {
    0x00: "STOP", 0x01: "ADD", 0x02: "MUL", 0x03: "SUB", 0x04: "DIV",
    0x05: "SDIV", 0x06: "MOD", 0x07: "SMOD", 0x08: "ADDMOD", 0x09: "MULMOD",
    0x0A: "EXP", 0x0B: "SIGNEXTEND", 0x10: "LT", 0x11: "GT", 0x12: "SLT",
    0x13: "SGT", 0x14: "EQ", 0x15: "ISZERO", 0x16: "AND", 0x17: "OR",
    0x18: "XOR", 0x19: "NOT", 0x1A: "BYTE", 0x1B: "SHL", 0x1C: "SHR",
    0x1D: "SAR", 0x20: "SHA3", 0x30: "ADDRESS", 0x31: "BALANCE",
    0x32: "ORIGIN", 0x33: "CALLER", 0x34: "CALLVALUE", 0x35: "CALLDATASIZE",
    0x36: "CALLDATACOPY", 0x37: "CODESIZE", 0x38: "CODECOPY", 0x39: "GASPRICE",
    0x3A: "EXTCODESIZE", 0x3B: "EXTCODECOPY", 0x3C: "RETURNDATASIZE",
    0x3D: "RETURNDATACOPY", 0x3E: "EXTCODEHASH", 0x40: "BLOCKHASH",
    0x41: "COINBASE", 0x42: "TIMESTAMP", 0x43: "NUMBER", 0x44: "PREVRANDAO",
    0x45: "GASLIMIT", 0x46: "CHAINID", 0x47: "SELFBALANCE", 0x48: "BASEFEE",
    0x49: "BLOBHASH", 0x4A: "BLOBBASEFEE", 0x50: "POP", 0x51: "MLOAD",
    0x52: "MSTORE", 0x53: "MSTORE8", 0x54: "SLOAD", 0x55: "SSTORE",
    0x56: "JUMP", 0x57: "JUMPI", 0x58: "PC", 0x59: "MSIZE", 0x5A: "GAS",
    0x5B: "JUMPDEST", 0xF0: "CREATE", 0xF1: "CALL", 0xF2: "CALLCODE",
    0xF3: "RETURN", 0xF4: "DELEGATECALL", 0xF5: "CREATE2", 0xFA: "STATICCALL",
    0xFD: "REVERT", 0xFE: "INVALID", 0xFF: "SELFDESTRUCT",
}
for _width in range(1, 33):
    _OPCODE_NAMES[0x5F + _width] = f"PUSH{_width}"
for _width in range(1, 17):
    _OPCODE_NAMES[0x7F + _width] = f"DUP{_width}"
    _OPCODE_NAMES[0x8F + _width] = f"SWAP{_width}"
_OPCODE_NAMES[0x5F] = "PUSH0"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def disassemble_opcode_names(bytecode_path: Path) -> tuple[str, ...]:
    """Return the unique opcode names in a bytecode stream, in sort order."""
    value = bytecode_path.read_text(encoding="utf-8").strip()
    if not value.startswith("0x"):
        raise ValueError(f"{bytecode_path}: bytecode must start with 0x")
    raw = bytes.fromhex(value[2:])
    used: set[str] = set()
    index = 0
    while index < len(raw):
        opcode = raw[index]
        used.add(_OPCODE_NAMES.get(opcode, f"0x{opcode:02x}"))
        index += 1
        if 0x60 <= opcode <= 0x7F:
            index += opcode - 0x5F
    return tuple(sorted(used))


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


def build_matrix(root: Path = ROOT) -> tuple[EVMExecutionSupportMatrix, dict[str, Any]]:
    root = root.resolve()
    artifact_root = root / ARTIFACT_REL
    harness_root = root / HARNESS_REL
    bytecode_path = artifact_root / "bytecode" / "CBridge.deployed.hex"
    source_path = harness_root / "contracts" / "CBridge.sol"
    manifest_path = harness_root / "source_manifest.json"
    profile_path = artifact_root / "channel_profile.json"
    for path in (bytecode_path, source_path, manifest_path, profile_path):
        if not path.is_file():
            raise ValueError(f"missing support-matrix input: {path}")

    manifest = _load_object(manifest_path)
    source_hash = sha256_file(source_path)
    bytecode_hash = sha256_file(bytecode_path)
    artifact_hash = sha256_file(artifact_root / "manifest.json")
    profile_hash = sha256_file(profile_path)
    manifest_hash = sha256_file(manifest_path)
    used_opcodes = disassemble_opcode_names(bytecode_path)
    used_set = set(used_opcodes)

    entries: list[SupportEntry] = []
    # This is the explicit development host scope.  The observed subset is
    # derived from bytecode, while the unobserved subset stays unknown.
    opcode_scope = (
        "CALLER", "CALLVALUE", "CALLDATASIZE", "CALLDATACOPY", "EXTCODEHASH",
        "RETURNDATASIZE", "RETURNDATACOPY", "CHAINID", "TIMESTAMP", "SELFBALANCE",
        "SHA3", "SLOAD", "SSTORE", "CALL", "DELEGATECALL", "STATICCALL",
        "CREATE", "CREATE2", "SELFDESTRUCT", "PUSH0",
    )
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

    # The Celer development artifact is explicitly non-upgradeable.  Generic
    # proxy support is conditional on carrying the implementation/configuration
    # hashes in the replay identity.
    entries.extend((
        _entry("proxy", "none", SupportStatus.SUPPORTED, evidence_hash=artifact_hash,
               note="deployment metadata declares is_proxy=false and has no initializer"),
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
            note="no precompile call site is admitted by the Celer development source/bytecode probe",
        ))

    entries.extend((
        _entry("crypto", "keccak256", SupportStatus.SUPPORTED, evidence_hash=source_hash,
               note="source-level hashlock and transfer-id derivations use keccak256"),
        _entry("crypto", "ecdsa_recover", SupportStatus.UNKNOWN, evidence_hash=source_hash,
               note="not used by the locked CBridge source; no host support claim"),
        _entry("crypto", "sha256", SupportStatus.UNKNOWN, evidence_hash=source_hash,
               note="not used by the locked CBridge source; no host support claim"),
        _entry("crypto", "ripemd160", SupportStatus.UNKNOWN, evidence_hash=source_hash,
               note="not used by the locked CBridge source; no host support claim"),
    ))

    matrix = EVMExecutionSupportMatrix(
        matrix_id="celer-cbridge-foundry-development-v1",
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
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "evm_execution_support_matrix",
        "scope": "source_backed_development_host_draft",
        "lineage_id": LINEAGE_ID,
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
    metadata["report_hash"] = sha256_hex(metadata)
    return matrix, metadata


def validate_report(root: Path = ROOT, report_path: Path | None = None) -> list[str]:
    root = root.resolve()
    path = report_path or root / DEFAULT_OUTPUT
    errors: list[str] = []
    try:
        report = _load_object(path)
        matrix, expected = build_matrix(root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"support matrix report unreadable: {error}"]

    stored_hash = report.get("report_hash")
    body = dict(report)
    body.pop("report_hash", None)
    if stored_hash != sha256_hex(body):
        errors.append("support matrix report hash mismatch")
    for key in (
        "schema_version", "record_type", "scope", "lineage_id", "source_repository",
        "source_commit", "source_manifest_sha256", "source_file_sha256",
        "artifact_manifest_sha256", "profile_sha256", "source_backed", "acceptance_status",
        "acceptance_owner", "accepted_at", "acceptance_agent", "independent_validation_required",
        "independent_differential_required", "admission_eligible",
        "evidence_scope",
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
        errors.append("matrix content does not match locked Celer inputs")
    if report.get("bytecode_opcode_scan") != expected.get("bytecode_opcode_scan"):
        errors.append("bytecode opcode scan mismatch")
    if report.get("matrix", {}).get("acceptance_status") != "draft":
        errors.append("development support matrix must remain draft")
    return errors


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.out.resolve() if args.out else root / DEFAULT_OUTPUT.relative_to(ROOT)
    try:
        if args.check:
            errors = validate_report(root, output)
            if errors:
                print("FAILED")
                print("\n".join(errors))
                return 1
            print("OK: Celer EVM support matrix is valid and remains draft/non-admission")
            return 0
        _, report = build_matrix(root)
        _atomic_json(output, report)
        print(f"support matrix written to: {output}")
        print(f"matrix_hash: {report['matrix']['matrix_hash']}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
