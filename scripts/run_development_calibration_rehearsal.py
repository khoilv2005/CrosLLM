#!/usr/bin/env python3
"""Run a deterministic, explicitly synthetic M10 calibration rehearsal.

This exercises the development selection, precision, budget and freeze
contracts without making a provider call.  The output is intentionally
non-admission and records zero executed provider calls; it is a pipeline
rehearsal, not a measured calibration result.
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

from crossllm.calibration import (
    BudgetInputs,
    CalibrationObservation,
    build_compact_calibration_menu,
    estimate_budget,
    freeze_development_selection,
    select_common_replicates,
    select_development_setting,
    PrecisionSimulationConfig,
    SelectionRule,
)
from crossllm.contracts.canonical import sha256_hex


DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "m10_development_calibration_rehearsal.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _fixture_observations() -> tuple[CalibrationObservation, ...]:
    # Ten calls per setting is the M10.02 rehearsal shape. Values are fixture
    # inputs, not provider observations, and are deliberately labeled below.
    return (
        CalibrationObservation("cal-low-t0.5", "development", 0.70, 0.01, 10),
        CalibrationObservation("cal-low-t0.9", "development", 0.72, 0.04, 10),
        CalibrationObservation("cal-high-t0.5", "development", 0.76, 0.02, 10),
        CalibrationObservation("cal-high-t0.9", "development", 0.77, 0.08, 10),
    )


def build_report(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    menu = build_compact_calibration_menu(
        reasoning_levels=("low", "high"),
        starting_temperature=0.7,
        temperature_delta=0.2,
        output_cap=8192,
        estimated_cost_usd={
            ("low", 0.5): 0.10,
            ("low", 0.9): 0.11,
            ("high", 0.5): 0.20,
            ("high", 0.9): 0.21,
        },
    )
    observations = _fixture_observations()
    selection = select_development_setting(
        list(menu),
        list(observations),
        rule=SelectionRule(recall_tolerance=0.02, max_truncation_rate=0.05),
    )
    precision_config = PrecisionSimulationConfig(
        {"dev-lineage-a": 2, "dev-lineage-b": 3, "dev-lineage-c": 1, "dev-lineage-d": 2},
        campaigns_per_instance=1,
        draws=1000,
        seed=20260909,
        target_recall_mcse=0.025,
        target_difference_mcse=0.03,
    )
    probabilities = {
        "dev-lineage-a": (0.55, 0.20, 0.10, 0.15),
        "dev-lineage-b": (0.45, 0.25, 0.10, 0.20),
        "dev-lineage-c": (0.50, 0.15, 0.20, 0.15),
        "dev-lineage-d": (0.40, 0.30, 0.10, 0.20),
    }
    replicate_selection = select_common_replicates(
        precision_config,
        joint_probabilities=probabilities,
        candidates=(5, 10, 20),
    )
    budget = estimate_budget(BudgetInputs(
        campaign_count=80,
        provider_calls_per_campaign=8,
        expected_input_tokens=1200,
        expected_generated_tokens=250,
        expected_retries_per_call=0.1,
        solver_core_seconds_per_campaign=30.0,
        baseline_campaign_count=32,
        calibration_campaign_count=160,
        adjudication_case_count=40,
        adjudication_seconds_per_case=180.0,
        input_cost_per_token=0.000001,
        generated_cost_per_token=0.000003,
    ))
    hash_inputs = {
        "protocol_hash": _sha256(root / "protocol" / "protocol.json"),
        "prompt_hash": _sha256(root / "prompts" / "manifest.json"),
        "primitives_hash": _sha256(root / "src" / "crossllm" / "xlir" / "primitives.py"),
        "mutation_policy_hash": _sha256(root / "dataset" / "benchmark" / "mutation_validation_spec.json"),
        "harness_policy_hash": _sha256(root / "docs" / "action_evidence.md"),
        "runtime_policy_hash": _sha256(root / "docs" / "runtime_events.md"),
        "analysis_code_hash": _sha256(root / "src" / "crossllm" / "analysis" / "estimands.py"),
    }
    freeze = freeze_development_selection(selection, hashes=hash_inputs)
    truncation = {
        row.setting_id: {
            "rate": row.truncation_rate,
            "threshold": 0.05,
            "exceeds_threshold": (row.truncation_rate or 0.0) > 0.05,
        }
        for row in observations
    }
    body: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "synthetic_development_calibration_rehearsal",
        "scope": "development_pipeline_rehearsal_only",
        "admission_eligible": False,
        "executed_provider_calls": 0,
        "synthetic_fixture_inputs": True,
        "menu": [setting.as_dict() for setting in menu],
        "observations": [
            {
                "setting_id": row.setting_id,
                "split": row.split,
                "recall": row.recall,
                "truncation_rate": row.truncation_rate,
                "calls": row.calls,
            }
            for row in observations
        ],
        "selection": selection.as_dict(),
        "truncation_diagnostics": truncation,
        "precision_config": {
            "instances_per_lineage": precision_config.instances_per_lineage,
            "campaigns_per_instance": precision_config.campaigns_per_instance,
            "draws": precision_config.draws,
            "seed": precision_config.seed,
            "target_recall_mcse": precision_config.target_recall_mcse,
            "target_difference_mcse": precision_config.target_difference_mcse,
        },
        "precision_inputs": {lineage: list(values) for lineage, values in probabilities.items()},
        "replicate_selection": replicate_selection.as_dict(),
        "budget": budget.as_dict(),
        "freeze": freeze.as_dict(),
        "hash_inputs": hash_inputs,
        "limitations": [
            "no provider calls were executed",
            "fixture observations are not model or raw campaign outcomes",
            "precision probabilities are planning assumptions",
            "freeze is development-only and has no named independent reviewer",
        ],
    }
    body["report_hash"] = sha256_hex(body)
    return body


def validate_report(root: Path = ROOT, report_path: Path | None = None) -> list[str]:
    root = root.resolve()
    path = report_path or DEFAULT_OUTPUT
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"calibration rehearsal unreadable: {error}"]
    if not isinstance(report, dict):
        return ["calibration rehearsal must be an object"]
    errors: list[str] = []
    body = dict(report)
    stored_hash = body.pop("report_hash", None)
    if stored_hash != sha256_hex(body):
        errors.append("calibration rehearsal report hash mismatch")
    expected = build_report(root)
    for key in (
        "schema_version", "record_type", "scope", "admission_eligible",
        "executed_provider_calls", "synthetic_fixture_inputs", "menu",
        "observations", "selection", "truncation_diagnostics", "precision_config",
        "precision_inputs", "replicate_selection", "budget", "freeze", "hash_inputs",
        "limitations",
    ):
        if report.get(key) != expected.get(key):
            errors.append(f"{key} mismatch")
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
        print("OK: synthetic development calibration rehearsal is valid and non-admission")
        return 0
    report = build_report(root)
    _atomic_json(output, report)
    print("synthetic development calibration rehearsal: 0 provider calls, non-admission")
    print(f"evidence written to: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
