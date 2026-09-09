#!/usr/bin/env python3
"""Generate and validate the six development replay negative controls."""

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
from crossllm.replay.negative_controls import CASE_IDS, build_report


DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "replay_negative_controls.json"
MUTATION_REPORT = ROOT / "dataset" / "reports" / "source_mutation_evidence.jsonl"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    return value


def validate_report(root: Path = ROOT, report_path: Path | None = None) -> list[str]:
    root = root.resolve()
    path = report_path or root / DEFAULT_OUTPUT.relative_to(ROOT)
    mutation_path = root / MUTATION_REPORT.relative_to(ROOT)
    errors: list[str] = []
    try:
        report = _load(path)
        expected = build_report(mutation_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"negative-control report unreadable: {error}"]
    body = dict(report)
    stored_hash = body.pop("report_hash", None)
    if stored_hash != sha256_hex(body):
        errors.append("negative-control report hash mismatch")
    for key in (
        "schema_version", "record_type", "scope", "case_ids", "case_count", "passed_count",
        "all_passed", "source_mutation_report_sha256", "source_backed",
        "independent_property_validation", "independent_trigger_validation",
        "admission_eligible", "evidence_scope",
    ):
        if report.get(key) != expected.get(key):
            errors.append(f"{key} mismatch")
    cases = report.get("cases")
    if not isinstance(cases, list):
        return errors + ["negative-control cases are missing"]
    if [row.get("case_id") for row in cases if isinstance(row, dict)] != list(CASE_IDS):
        errors.append("negative-control case coverage/order mismatch")
    if len(cases) != len(CASE_IDS):
        errors.append("negative-control case count mismatch")
    for row in cases:
        if not isinstance(row, dict):
            errors.append("negative-control row is not an object")
            continue
        if row.get("passed") is not True:
            errors.append(f"negative-control did not pass: {row.get('case_id')}")
        if not isinstance(row.get("observed_reason"), str) or not row["observed_reason"]:
            errors.append(f"negative-control reason missing: {row.get('case_id')}")
    if report.get("cases") != expected.get("cases"):
        errors.append("negative-control observations do not match current fixture/source evidence")
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
            print("OK: six replay negative controls are valid and development-only")
            return 0
        report = build_report(root / MUTATION_REPORT.relative_to(ROOT))
        _atomic_json(output, report)
        print(f"replay negative-control report: {report['passed_count']}/{report['case_count']} pass")
        print(f"evidence written to: {output}")
        return 0 if report["all_passed"] else 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
