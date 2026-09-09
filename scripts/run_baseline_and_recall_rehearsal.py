#!/usr/bin/env python3
"""Rehearse the outcome-blind M07 subsets and separated recall endpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossllm.analysis import BatchAvailability, EndToEndObservation, ProposalBatch, end_to_end_budget_recall, proposal_prefix_recall
from crossllm.baselines import select_balanced_subset
from crossllm.contracts.canonical import sha256_hex

PUBLIC_MANIFEST = ROOT / "benchmark.public.jsonl"
SELECTION_OUTPUT = ROOT / "dataset" / "reports" / "m07_selection_rehearsal.json"
RECALL_OUTPUT = ROOT / "dataset" / "reports" / "m07_recall_rehearsal.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_public_metadata(path: Path = PUBLIC_MANIFEST) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"manifest line {line_number} must be an object")
        cohort = value.get("cohort")
        family = value.get("property_family")
        if cohort not in {"sealed", "negative"} or not isinstance(family, str) or not family:
            raise ValueError(f"manifest line {line_number} lacks registered strata")
        rows.append({
            "instance_id": value.get("instance_id"),
            "lineage_id": value.get("lineage_id"),
            "family": family,
            "ground_truth": "positive" if cohort == "sealed" else "negative",
            "registered_cohort": cohort,
        })
    if not rows:
        raise ValueError("public manifest is empty")
    return tuple(rows)


def build_selection_report(root: Path = ROOT) -> dict[str, object]:
    root = root.resolve()
    manifest = root / PUBLIC_MANIFEST.relative_to(ROOT)
    rows = _load_public_metadata(manifest)
    baseline = select_balanced_subset(rows, target_size=48, seed=20260909, min_lineages=12, min_families=6, balance_fields=("registered_cohort",))
    sensitivity = select_balanced_subset(rows, target_size=24, seed=20260910, min_lineages=8, min_families=6, balance_fields=("registered_cohort",))
    body: dict[str, object] = {
        "schema_version": 1,
        "record_type": "synthetic_m07_selection_rehearsal",
        "scope": "development_selection_rehearsal_only",
        "input_manifest_sha256": _sha256(manifest),
        "outcome_blind": True,
        "provider_calls": 0,
        "admission_eligible": False,
        "baseline_subset": baseline.as_dict(),
        "sensitivity_subset": sensitivity.as_dict(),
        "backbones": ["Qwen", "gpt-oss"],
        "limitations": [
            "public manifest rows are structural development fixtures, not admitted benchmark cases",
            "cohort-to-ground-truth mapping is registered construction metadata, not a model outcome",
            "no method support was assumed and no provider calls were executed",
            "selection has no independent reviewer sign-off and cannot unlock evaluation",
        ],
    }
    body["report_hash"] = sha256_hex(body)
    return body


def build_recall_report() -> dict[str, object]:
    batches = (
        ProposalBatch("batch-1", "instance-1", ("q-no", "q-hit", "q-other"), ("q-hit",)),
        ProposalBatch("batch-2", "instance-2", ("q-hit", "q-other"), ("q-hit",)),
        ProposalBatch("batch-3", "instance-3", ("q-no", "q-other"), ("q-hit",)),
        ProposalBatch("batch-4", "instance-4", (), (), BatchAvailability.MISSING, "response_archive_missing"),
    )
    prefix = proposal_prefix_recall(batches, prefixes=(1, 2, 4, 8))
    observations = tuple(
        EndToEndObservation(f"observation-{budget}-{index}", f"instance-{index}", budget, detected=(index % 2 == 0) if budget < 8 else True)
        for budget in (1, 2, 4)
        for index in (1, 2)
    ) + (
        EndToEndObservation("observation-8-1", "instance-1", 8, True),
        EndToEndObservation("observation-8-2", "instance-2", 8, None, BatchAvailability.MISSING, "campaign_timeout"),
    )
    end_to_end = end_to_end_budget_recall(observations, budgets=(1, 2, 4, 8))
    body: dict[str, object] = {
        "schema_version": 1,
        "record_type": "synthetic_m07_recall_rehearsal",
        "scope": "development_recall_rehearsal_only",
        "synthetic_fixture_inputs": True,
        "provider_calls": 0,
        "admission_eligible": False,
        "proposal_prefix": prefix.as_dict(),
        "end_to_end": end_to_end.as_dict(),
        "endpoint_separation": True,
        "limitations": [
            "proposal batches and scheduled observations are synthetic fixtures",
            "prefix recall never inspects end-to-end outcomes and end-to-end recall never inspects proposal order",
            "no provider calls or evaluation labels were executed",
        ],
    }
    body["report_hash"] = sha256_hex(body)
    return body


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _validate_hash(report: dict[str, object], label: str) -> list[str]:
    body = dict(report)
    supplied = body.pop("report_hash", None)
    return [] if supplied == sha256_hex(body) else [f"{label} report hash mismatch"]


def validate_selection_report(root: Path = ROOT, path: Path = SELECTION_OUTPUT) -> list[str]:
    root = root.resolve()
    try:
        report = _load(path.resolve())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"selection rehearsal unreadable: {error}"]
    errors = _validate_hash(report, "selection")
    expected = build_selection_report(root)
    for key, value in expected.items():
        if key != "report_hash" and report.get(key) != value:
            errors.append(f"selection {key} mismatch")
    baseline = report.get("baseline_subset")
    sensitivity = report.get("sensitivity_subset")
    if not isinstance(baseline, dict) or baseline.get("target_size") != 48 or baseline.get("seed") != 20260909:
        errors.append("baseline subset is not the frozen 48-instance contract")
    if not isinstance(sensitivity, dict) or sensitivity.get("target_size") != 24 or sensitivity.get("seed") != 20260910:
        errors.append("sensitivity subset is not the frozen 24-instance contract")
    return errors


def validate_recall_report(path: Path = RECALL_OUTPUT) -> list[str]:
    try:
        report = _load(path.resolve())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"recall rehearsal unreadable: {error}"]
    errors = _validate_hash(report, "recall")
    expected = build_recall_report()
    for key, value in expected.items():
        if key != "report_hash" and report.get(key) != value:
            errors.append(f"recall {key} mismatch")
    if report.get("endpoint_separation") is not True:
        errors.append("proposal and end-to-end recall endpoints are not separated")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--selection-out", type=Path, default=None)
    parser.add_argument("--recall-out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    selection_path = args.selection_out.resolve() if args.selection_out else root / SELECTION_OUTPUT.relative_to(ROOT)
    recall_path = args.recall_out.resolve() if args.recall_out else root / RECALL_OUTPUT.relative_to(ROOT)
    if args.check:
        errors = validate_selection_report(root, selection_path) + validate_recall_report(recall_path)
        if errors:
            print("FAILED")
            print("\n".join(errors))
            return 1
        print("OK: M07 selection and separated recall rehearsals are valid and non-admission")
        return 0
    selection = build_selection_report(root)
    recall = build_recall_report()
    selection_path.parent.mkdir(parents=True, exist_ok=True)
    recall_path.parent.mkdir(parents=True, exist_ok=True)
    selection_path.write_text(json.dumps(selection, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    recall_path.write_text(json.dumps(recall, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("M07 selection rehearsal: 48-instance baseline + 24-instance sensitivity")
    print("M07 recall rehearsal: proposal-prefix and end-to-end endpoints remain separate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
