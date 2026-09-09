#!/usr/bin/env python3
"""Build and validate the development symbolic-to-source correspondence spike.

The report intentionally distinguishes structural correspondence from an
independent differential result.  It consumes the already validated
source-backed Celer receipt, re-runs the bounded symbolic fixture cases, and
records unsupported source semantics instead of inventing an EVM trace.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossllm.contracts.canonical import sha256_hex
from crossllm.replay.differential import build_cases


DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "symbolic_to_source_differential.json"
SOURCE_REPLAY_REL = Path("dataset") / "reports" / "source_backed_replay.json"
SUPPORT_MATRIX_REL = Path("dataset") / "reports" / "evm_support_matrix_celer_cbridge.json"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    return value


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_report(root: Path = ROOT, *, observed_at: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    source_path = root / SOURCE_REPLAY_REL
    matrix_path = root / SUPPORT_MATRIX_REL
    source_report = _load(source_path)
    matrix_report = _load(matrix_path)
    matrix = matrix_report.get("matrix")
    if not isinstance(matrix, dict) or not isinstance(matrix.get("matrix_hash"), str):
        raise ValueError("support matrix has no matrix_hash")
    cases = [case.as_dict() for case in build_cases()]
    body: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "development_symbolic_to_source_differential_spike",
        "scope": "development_structural_correspondence_only",
        "lineage_id": "celer_cbridge",
        "symbolic_engine": "z3-bounded-paired-v1",
        "source_engine": "foundry-native-celer-development-harness",
        "source_replay_report": str(SOURCE_REPLAY_REL).replace("\\", "/"),
        "source_replay_report_hash": source_report.get("report_hash"),
        "support_matrix_hash": matrix["matrix_hash"],
        "source_replay_status": source_report.get("result", {}).get("status"),
        "source_test_count": source_report.get("result", {}).get("test_count"),
        "case_count": len(cases),
        "cases": cases,
        "unsupported_fixture_semantics": [
            "cryptographic_preimage_validation",
            "revert_reason_and_failed_transaction_trace",
            "token_balance_conservation",
            "timelock_arithmetic",
            "source_contract_storage_layout",
        ],
        "differential_status": "structural_only",
        "direct_trace_comparable": False,
        "independent_evaluator": False,
        "independent_property_validation": False,
        "independent_trigger_validation": False,
        "reviewed_support_matrix": False,
        "admission_eligible": False,
        "evidence_scope": "development_spike_non_admission",
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    body["report_hash"] = sha256_hex(body)
    return body


def validate_report(root: Path = ROOT, report_path: Path | None = None) -> list[str]:
    root = root.resolve()
    path = report_path or root / DEFAULT_OUTPUT.relative_to(ROOT)
    errors: list[str] = []
    try:
        report = _load(path)
        expected = build_report(root, observed_at=report.get("observed_at"))
        source_report = _load(root / SOURCE_REPLAY_REL)
        matrix_report = _load(root / SUPPORT_MATRIX_REL)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"differential spike report unreadable: {error}"]

    body = dict(report)
    stored_hash = body.pop("report_hash", None)
    if stored_hash != sha256_hex(body):
        errors.append("differential spike report hash mismatch")
    for key in (
        "schema_version", "record_type", "scope", "lineage_id", "symbolic_engine",
        "source_engine", "source_replay_report", "support_matrix_hash", "case_count",
        "cases", "unsupported_fixture_semantics", "differential_status",
        "direct_trace_comparable", "independent_evaluator", "independent_property_validation",
        "independent_trigger_validation", "reviewed_support_matrix", "admission_eligible",
        "evidence_scope",
    ):
        if report.get(key) != expected.get(key):
            errors.append(f"{key} mismatch")
    if report.get("source_replay_report_hash") != source_report.get("report_hash"):
        errors.append("source replay report hash mismatch")
    if report.get("source_replay_status") != "pass" or report.get("source_test_count") != 3:
        errors.append("source-backed replay does not provide the expected 3/3 development receipt")
    if report.get("support_matrix_hash") != matrix_report.get("matrix", {}).get("matrix_hash"):
        errors.append("support matrix hash mismatch")
    if not isinstance(report.get("observed_at"), str) or not report["observed_at"].endswith("Z"):
        errors.append("observed_at is not a UTC timestamp")
    return errors


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
            print("OK: symbolic-to-source differential spike is valid and non-admission")
            return 0
        report = build_report(root)
        _atomic_json(output, report)
        print(f"symbolic-to-source differential spike: {report['case_count']} cases, structural-only")
        print(f"evidence written to: {output}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
