#!/usr/bin/env python3
"""Run the complete synthetic M09 adjudication/analysis rehearsal.

This command exercises the analysis boundary with deliberately synthetic raw
rows.  It emits CSV/SVG artifacts and provenance hashes, but never labels the
real benchmark, calls Ollama Cloud, or asserts evaluation admission.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossllm.adjudication import (
    AdjudicationLedger,
    BlindedFinding,
    FirstFailure,
    Label,
    LabelStatus,
    MappingStatus,
    RequirementMapping,
)
from crossllm.analysis import (
    AnalysisArtifact,
    AnalysisArtifactBuilder,
    AnalysisFigureBuilder,
    agreement_summary,
    leave_one_lineage_out,
    stratified_sample,
    write_figure_bundle,
    zero_event_upper_bound,
)
from crossllm.contracts.canonical import sha256_hex


DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "m09_analysis_rehearsal.json"
ANALYSIS_BUNDLE = ROOT / "dataset" / "reports" / "m09_analysis_bundle"
FIGURE_BUNDLE = ROOT / "dataset" / "reports" / "m09_figures"


def _synthetic_rows() -> tuple[dict[str, object], ...]:
    """Create unequal lineage sizes and explicit missing/failure outcomes."""
    sizes = {"lineage-a": 2, "lineage-b": 3, "lineage-c": 2, "lineage-d": 4}
    rows: list[dict[str, object]] = []
    for lineage, size in sizes.items():
        for instance_number in range(1, size + 1):
            instance = f"{lineage}-instance-{instance_number}"
            truth = "positive" if instance_number % 2 else "negative"
            for method in ("X", "P", "T0"):
                for replicate in (1, 2):
                    provider_failure = lineage == "lineage-c" and method == "P" and replicate == 2
                    if provider_failure:
                        detected = None
                        useful = None
                        claim = None
                        correct = None
                        witness = None
                        replay = None
                        claim_time = None
                        witness_time = None
                        availability = "provider_failure"
                    else:
                        # The pattern is fixed by pre-outcome fixture identity,
                        # not by a result-dependent selection rule.
                        detected = truth == "positive" and (
                            method == "X" or (method == "P" and instance_number == 1) or replicate == 1
                        )
                        useful = detected
                        claim = detected if truth == "positive" else method == "X" and instance_number % 2 == 0
                        correct = (not claim) if truth == "negative" else claim
                        witness = detected and method != "T0"
                        replay = witness and method == "X"
                        claim_time = float(2 + replicate + instance_number) if claim else None
                        witness_time = float(1 + replicate) if witness else None
                        availability = "available"
                    rows.append({
                        "campaign_id": f"{method}-{lineage}-{instance_number}-r{replicate}",
                        "instance_id": instance,
                        "lineage_id": lineage,
                        "method": method,
                        "replicate": replicate,
                        "ground_truth": truth,
                        "detected": detected,
                        "useful_proposal": useful,
                        "claim_emitted": claim,
                        "correct_claim": correct,
                        "native_witness": witness,
                        "independent_replay": replay,
                        "claim_time_seconds": claim_time,
                        "witness_time_seconds": witness_time,
                        "horizon_seconds": 60.0,
                        "availability": availability,
                        "first_failure": "provider_failure" if provider_failure else None,
                    })
    return tuple(rows)


def _adjudication() -> tuple[AdjudicationLedger, dict[str, object]]:
    findings = [
        BlindedFinding("finding-1", "lineage-a-instance-1", {"property": "replay", "claim": "violation"}, "e" * 64, "r" * 64, "root-1"),
        BlindedFinding("finding-2", "lineage-b-instance-1", {"property": "finality", "claim": "violation"}, "f" * 64, "s" * 64, "root-2"),
        # Same instance/root cause demonstrates deduplication without deleting
        # the original finding record.
        BlindedFinding("finding-3", "lineage-a-instance-1", {"property": "replay", "claim": "duplicate"}, "g" * 64, "t" * 64, "root-1"),
    ]
    ledger = AdjudicationLedger(findings)
    fixed_1 = "2026-09-09T00:00:01Z"
    fixed_2 = "2026-09-09T00:00:02Z"
    ledger.add_label(Label("finding-1", "rater-a", "rater", LabelStatus.CONFIRMED, FirstFailure.TRUE_VULNERABILITY, confidence="high", created_at=fixed_1))
    ledger.add_label(Label("finding-1", "rater-b", "reviewer", LabelStatus.CONFIRMED, FirstFailure.TRUE_VULNERABILITY, confidence="high", created_at=fixed_2))
    ledger.add_label(Label("finding-2", "rater-a", "rater", LabelStatus.CONFIRMED, FirstFailure.TRUE_VULNERABILITY, confidence="medium", created_at=fixed_1))
    ledger.add_label(Label("finding-2", "rater-b", "reviewer", LabelStatus.REJECTED, FirstFailure.UNWARRANTED_PROPERTY, confidence="medium", created_at=fixed_2))
    first = ledger.reconcile("finding-1", adjudicator_id="rater-c", reason="Both raters independently confirmed the same claim.", created_at="2026-09-09T00:00:03Z")
    second = ledger.reconcile(
        "finding-2",
        adjudicator_id="rater-c",
        reason="Raters disagree on property validity; preserve uncertainty.",
        uncertainty_reason="Independent labels disagree and no consensus evidence is supplied in this fixture.",
        created_at="2026-09-09T00:00:04Z",
    )
    ledger.relabel("finding-2", LabelStatus.UNRESOLVED, actor_id="rater-c", reason="Keep disagreement unresolved for sensitivity analysis.", created_at="2026-09-09T00:00:05Z")
    ledger.map_requirement(RequirementMapping("finding-1", "EG-replay-01", MappingStatus.MAPPED, "reviewer-j", "Blind mapping from claim to prespecified requirement.", "2026-09-09T00:00:06Z"))
    ledger.map_requirement(RequirementMapping("finding-2", None, MappingStatus.UNCERTAIN, "reviewer-j", "No requirement mapping is asserted while the label is unresolved.", "2026-09-09T00:00:07Z"))
    left = {label.finding_id: label.status.value for label in ledger.labels if label.rater_id == "rater-a"}
    right = {label.finding_id: label.status.value for label in ledger.labels if label.rater_id == "rater-b"}
    agreement = agreement_summary(left, right, clusters={"finding-1": "lineage-a", "finding-2": "lineage-b"}, draws=1000, seed=20260909)
    payload = {
        "finding_count": len(ledger.findings),
        "label_count": len(ledger.labels),
        "reconciliation_count": len(ledger.reconciliations),
        "relabel_count": len(ledger.relabel_history),
        "requirement_mapping_count": len(ledger.requirement_mappings),
        "deduplicated_finding_ids": list(ledger.deduplicated_finding_ids()),
        "first_reconciliation_status": first.status.value,
        "second_reconciliation_status": second.status.value,
        # Normalize tuple-valued confidence intervals to the JSON form before
        # hashing, so in-memory and archived reports compare identically.
        "agreement": json.loads(json.dumps(agreement.as_dict())),
        "taxonomy_classes": [failure.value for failure in FirstFailure],
        "ledger_hash": ledger.as_dict()["ledger_hash"],
    }
    return ledger, payload


def _inference_inputs() -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    lineages = ("lineage-a", "lineage-b", "lineage-c", "lineage-d")
    primary = {
        f"primary-{index}": {lineage: ((index + offset) % 3 - 1) / 2 for offset, lineage in enumerate(lineages)}
        for index in range(5)
    }
    secondary = {
        f"secondary-{index}": {lineage: ((index * 2 + offset) % 4 - 1.5) / 3 for offset, lineage in enumerate(lineages)}
        for index in range(6)
    }
    return primary, secondary


def _build_core(root: Path) -> tuple[AnalysisArtifact, dict[str, object], dict[str, object], tuple[Any, ...], dict[str, object]]:
    rows = _synthetic_rows()
    primary, secondary = _inference_inputs()
    artifact = AnalysisArtifactBuilder().build(
        rows,
        primary_contrasts=primary,
        secondary_contrasts=secondary,
        draws=10_000,
        seed=20260909,
        require_prespecified_families=True,
    )
    ledger, adjudication = _adjudication()
    records = [
        {"id": f"accepted-{index}", "kind": "accepted", "lineage": f"lineage-{index % 2}"}
        for index in range(4)
    ] + [
        {"id": f"rejected-{index}", "kind": "rejected", "lineage": f"lineage-{index % 3}"}
        for index in range(8)
    ]
    sample = stratified_sample(
        records,
        record_id=lambda row: row["id"],
        stratum=lambda row: row["kind"],
        sample_size_by_stratum={"accepted": 2, "rejected": 4},
        seed=20260909,
    )
    effects = primary["primary-0"]
    figures = AnalysisFigureBuilder().build(
        paired_lineage=effects,
        recall_at_n={"X": {1: 0.25, 2: 0.50, 4: 0.75, 8: 0.75}, "P": {1: 0.10, 2: 0.25, 4: 0.40, 8: 0.50}},
        time_curves={"X": ((0.0, 0.0), (10.0, 0.5), (30.0, 0.8)), "P": ((0.0, 0.0), (10.0, 0.3), (30.0, 0.5))},
        scaling={"X": {1: 0.2, 2: 0.4, 4: 0.7}, "P": {1: 0.1, 2: 0.2, 4: 0.4}},
        failure_flow={"malformed": 1, "timeout": 2, "replay_failure": 1, "confirmed": 3},
    )
    inference = {
        "primary_count": len(artifact.primary_inference),
        "secondary_count": len(artifact.secondary_inference),
        "bootstrap_draws": artifact.primary_inference[0].bootstrap.draws,
        "primary_holm_scope": "primary_only",
        "secondary_holm_scope": "secondary_only",
        "zero_event_upper_bound_n4": zero_event_upper_bound(4),
        "leave_one_lineage_out": leave_one_lineage_out(primary["primary-0"]),
    }
    sampling = {
        "population_count": len(records),
        "accepted_population": 4,
        "rejected_population": 8,
        "sample_count": len(sample),
        "sampled_ids": [row.record_id for row in sample],
        "weights": [row.weight for row in sample],
        "seed": 20260909,
    }
    return artifact, adjudication, sampling, figures, inference


def build_report(root: Path = ROOT) -> dict[str, object]:
    artifact, adjudication, sampling, figures, inference = _build_core(root.resolve())
    body: dict[str, object] = {
        "schema_version": 1,
        "record_type": "synthetic_m09_analysis_rehearsal",
        "scope": "development_analysis_rehearsal_only",
        "synthetic_fixture_inputs": True,
        "provider_calls": 0,
        "admission_eligible": False,
        "analysis": {
            "row_count": artifact.row_count,
            "input_hash": artifact.input_hash,
            "artifact_hash": artifact.artifact_hash,
            "table_count": len(artifact.tables),
            "table_ids": [table.table_id for table in artifact.tables],
            "primary_contrast_count": len(artifact.primary_inference),
            "secondary_contrast_count": len(artifact.secondary_inference),
        },
        "adjudication": adjudication,
        "sampling": sampling,
        "inference": inference,
        "figures": [figure.as_dict() for figure in figures],
        "limitations": [
            "all campaign rows, labels, and figure series are synthetic fixtures",
            "provider calls executed: 0; no Ollama Cloud response is represented",
            "no independent reviewer or evaluation-admission evidence is created",
        ],
    }
    body["report_hash"] = sha256_hex(body)
    return body


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(root: Path = ROOT, output: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    root = root.resolve()
    output = output.resolve()
    artifact, _adjudication, _sampling, figures, _inference = _build_core(root)
    analysis_manifest = artifact.write_bundle(ANALYSIS_BUNDLE)
    figure_manifest = write_figure_bundle(figures, FIGURE_BUNDLE)
    report = build_report(root)
    report["outputs"] = {
        "analysis_bundle_dir": str(ANALYSIS_BUNDLE.relative_to(root)).replace("\\", "/"),
        "analysis_manifest_sha256": _sha256(analysis_manifest),
        "figure_bundle_dir": str(FIGURE_BUNDLE.relative_to(root)).replace("\\", "/"),
        "figure_manifest_sha256": _sha256(figure_manifest),
    }
    report["report_hash"] = sha256_hex({key: value for key, value in report.items() if key != "report_hash"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def validate_report(root: Path = ROOT, report_path: Path = DEFAULT_OUTPUT) -> list[str]:
    root = root.resolve()
    try:
        report = json.loads(report_path.resolve().read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"analysis rehearsal unreadable: {error}"]
    if not isinstance(report, dict):
        return ["analysis rehearsal must be an object"]
    errors: list[str] = []
    unsigned = dict(report)
    supplied_hash = unsigned.pop("report_hash", None)
    if supplied_hash != sha256_hex(unsigned):
        errors.append("analysis rehearsal report hash mismatch")
    expected = build_report(root)
    for key, value in expected.items():
        if key == "report_hash":
            continue
        if report.get(key) != value:
            errors.append(f"{key} mismatch")
    outputs = report.get("outputs")
    if not isinstance(outputs, dict):
        return errors + ["outputs are missing"]
    analysis_dir = root / str(outputs.get("analysis_bundle_dir", ""))
    figure_dir = root / str(outputs.get("figure_bundle_dir", ""))
    analysis_manifest = analysis_dir / "manifest.json"
    figure_manifest = figure_dir / "figures.json"
    if not analysis_manifest.is_file() or outputs.get("analysis_manifest_sha256") != _sha256(analysis_manifest):
        errors.append("analysis bundle manifest is missing or hash-mismatched")
    else:
        try:
            manifest = json.loads(analysis_manifest.read_text(encoding="utf-8"))
            for row in manifest.get("tables", []):
                table_path = analysis_dir / str(row.get("path", ""))
                if not table_path.is_file() or row.get("sha256") != _sha256(table_path):
                    errors.append(f"analysis table missing or hash-mismatched: {table_path.name}")
        except (OSError, json.JSONDecodeError, AttributeError):
            errors.append("analysis bundle manifest is malformed")
    if not figure_manifest.is_file() or outputs.get("figure_manifest_sha256") != _sha256(figure_manifest):
        errors.append("figure bundle manifest is missing or hash-mismatched")
    else:
        try:
            manifest = json.loads(figure_manifest.read_text(encoding="utf-8"))
            for row in manifest.get("figures", []):
                figure_id = row.get("figure_id")
                figure_path = figure_dir / f"{figure_id}.svg"
                if not figure_path.is_file() or row.get("svg_hash") != sha256_hex(figure_path.read_text(encoding="utf-8")):
                    errors.append(f"figure missing or hash-mismatched: {figure_id}")
        except (OSError, json.JSONDecodeError, AttributeError):
            errors.append("figure bundle manifest is malformed")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.out.resolve() if args.out else root / DEFAULT_OUTPUT.relative_to(ROOT)
    if args.check:
        errors = validate_report(root, output)
        if errors:
            print("FAILED")
            print("\n".join(errors))
            return 1
        print("OK: synthetic M09 analysis rehearsal is valid and non-admission")
        return 0
    report = run(root, output)
    print(f"synthetic M09 analysis rehearsal: {report['analysis']['row_count']} rows, 11 tables, 5 figures")
    print("provider calls: 0; evaluation admission: false")
    print(f"evidence written to: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
