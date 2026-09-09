#!/usr/bin/env python3
"""Produce a fail-closed mechanical review of historical candidates.

The public inventory contains leads, not independently reproducible cases.
This tool turns missing admission evidence into explicit per-case gates. It
never upgrades a record to ``admitted`` and never treats a generated artifact,
incident summary, or transaction link as proof of a vulnerable revision,
trigger, control, or native paired-EVM replay.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_INPUT = Path("dataset/cases/historical_candidates.jsonl")
DEFAULT_REGISTRY = Path("dataset/sources/source_registry.json")
DEFAULT_OUTPUT = Path("dataset/reports/historical_candidate_reviews.jsonl")
REQUIRED_EVIDENCE_GATES = (
    "native_evm_eligibility",
    "vulnerable_revision",
    "patched_revision",
    "trigger_validation",
    "matched_control",
    "threat_assumptions",
)


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {error.msg}") from error
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected an object")
        rows.append(value)
    return rows


def _pending_gate(reason: str) -> dict[str, Any]:
    return {"status": "pending", "evidence_refs": [], "reason": reason}


def _case_gate(case: dict[str, Any], field: str) -> dict[str, Any]:
    """Accept only explicit, referenced pass evidence supplied by a reviewer."""

    value = case.get(field)
    if not isinstance(value, dict):
        return _pending_gate(f"missing structured {field} evidence")
    status = value.get("status")
    refs = value.get("evidence_refs")
    reason = value.get("reason")
    if status not in {"pass", "fail", "pending"}:
        return _pending_gate(f"{field} evidence has no recognized status")
    if not isinstance(refs, list) or not all(
        isinstance(ref, str) and ref for ref in refs
    ):
        return _pending_gate(f"{field} evidence_refs are missing or malformed")
    if not isinstance(reason, str) or not reason:
        return _pending_gate(f"{field} evidence has no reason")
    return {"status": status, "evidence_refs": list(refs), "reason": reason}


def _source_gate(case: dict[str, Any], source_ids: set[str]) -> dict[str, Any]:
    values = case.get("source_ids")
    if not isinstance(values, list) or not values or not all(
        isinstance(item, str) and item for item in values
    ):
        return {
            "status": "fail",
            "evidence_refs": [],
            "reason": "source_ids is missing or malformed",
        }
    unknown = sorted(set(values) - source_ids)
    if unknown:
        return {
            "status": "fail",
            "evidence_refs": [],
            "reason": f"source_ids are not present in source registry: {', '.join(unknown)}",
        }
    return {
        "status": "pass",
        "evidence_refs": [
            f"dataset/sources/source_registry.json#{item}" for item in values
        ],
        "reason": "all source identifiers resolve to the canonical source registry",
    }


def _lineage_gate(
    case: dict[str, Any], cases_by_lineage: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    lineage = case.get("lineage_id")
    related = [
        item.get("case_id")
        for item in cases_by_lineage.get(lineage, [])
        if item.get("case_id") != case.get("case_id")
    ]
    related = sorted(item for item in related if isinstance(item, str))
    if related:
        return {
            "status": "fail",
            "related_case_ids": related,
            "reason": "multiple historical records share this lineage and cannot be counted as independent samples",
        }
    return {
        "status": "pending",
        "related_case_ids": [],
        "reason": "split/lineage independence has not been assigned and reviewed",
    }


def review_cases(
    cases: list[dict[str, Any]], registry: dict[str, Any]
) -> list[dict[str, Any]]:
    source_entries = registry.get("sources")
    if not isinstance(source_entries, list):
        raise ValueError("source registry has no sources array")
    source_ids = {
        item.get("source_id")
        for item in source_entries
        if isinstance(item, dict) and isinstance(item.get("source_id"), str)
    }
    registry_hash = canonical_hash(registry)
    cases_by_lineage: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        lineage = case.get("lineage_id")
        if isinstance(lineage, str):
            cases_by_lineage.setdefault(lineage, []).append(case)

    rows: list[dict[str, Any]] = []
    for case in sorted(cases, key=lambda item: str(item.get("case_id", ""))):
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("historical candidate is missing case_id")
        gates: dict[str, dict[str, Any]] = {
            "source_registry_binding": _source_gate(case, source_ids)
        }
        gates.update({field: _case_gate(case, field) for field in REQUIRED_EVIDENCE_GATES})
        lineage_independence = _lineage_gate(case, cases_by_lineage)
        blocking_reasons = [
            f"{name}: {gate['reason']}"
            for name, gate in gates.items()
            if gate["status"] != "pass"
        ]
        if lineage_independence["status"] != "pass":
            blocking_reasons.append(
                f"lineage_independence: {lineage_independence['reason']}"
            )
        original_status = case.get("admission_status")
        admission_status = (
            original_status if original_status in {"candidate", "rejected"} else "candidate"
        )
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "case_id": case_id,
                "protocol": case.get("protocol", ""),
                "lineage_id": case.get("lineage_id", ""),
                "source_ids": list(case.get("source_ids", []))
                if isinstance(case.get("source_ids"), list)
                else [],
                "case_snapshot_sha256": canonical_hash(case),
                "source_registry_snapshot_sha256": registry_hash,
                "review_mode": "mechanical_fail_closed",
                "admission_status": admission_status,
                "admission_eligible": False,
                "gates": gates,
                "lineage_independence": lineage_independence,
                "blocking_reasons": blocking_reasons
                or ["no blocking reason recorded; human review is still required"],
                "evidence_scope": [
                    "dataset/cases/historical_candidates.jsonl",
                    "dataset/sources/source_registry.json",
                ],
            }
        )
    return rows


def validate_report(root: Path, report_path: Path | None = None) -> list[str]:
    input_path = root / DEFAULT_INPUT
    registry_path = root / DEFAULT_REGISTRY
    output_path = report_path or (root / DEFAULT_OUTPUT)
    try:
        cases = read_jsonl(input_path)
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        actual = read_jsonl(output_path)
        expected = review_cases(cases, registry)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [str(error)]
    errors: list[str] = []
    if actual != expected:
        errors.append(
            f"{output_path.relative_to(root)} does not match deterministic candidate review"
        )
    if len(actual) != len(cases):
        errors.append(
            f"candidate review count {len(actual)} does not match candidate count {len(cases)}"
        )
    for row in actual:
        if row.get("admission_eligible") is not False:
            errors.append(f"{row.get('case_id', '<unknown>')}: admission_eligible must remain false")
    return errors


def write_report(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows
    )
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--check", action="store_true", help="validate the existing deterministic report"
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.output.resolve() if args.output else root / DEFAULT_OUTPUT
    if args.check:
        errors = validate_report(root, output)
        if errors:
            print("FAILED")
            print("\n".join(errors))
            return 1
        print(
            f"OK: {len(read_jsonl(output))} historical candidate reviews; all remain non-admission"
        )
        return 0
    cases = read_jsonl(root / DEFAULT_INPUT)
    registry = json.loads((root / DEFAULT_REGISTRY).read_text(encoding="utf-8"))
    rows = review_cases(cases, registry)
    write_report(output, rows)
    print(f"WROTE: {output.relative_to(root)} ({len(rows)} candidates; admission_eligible=false)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
