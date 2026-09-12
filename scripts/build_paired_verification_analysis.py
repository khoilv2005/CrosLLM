#!/usr/bin/env python3
"""Build one deterministic analysis bundle from shared verification outcomes.

The input is the immutable ``verification_campaign`` JSONL emitted by the
shared verification runner.  This command is deliberately downstream-only:
it never turns a proposal archive into a verified finding and never replaces
missing, unsupported, timeout or unknown stages with negative outcomes.

The same campaign input is projected at every requested proposal prefix.  Raw
verification metrics, method-level analysis rows and optional paired effects
are emitted together so CrossLLM, Direct and T0 can use the same statistics
boundary.  Use ``--compare`` more than once when more than one paired contrast
is required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean
import sys
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from crossllm.analysis import AnalysisArtifactBuilder, campaigns_to_analysis_outcomes
from crossllm.contracts.canonical import sha256_hex
from crossllm.verification.metrics import VerificationCampaign, compute_verification_metrics

from scripts.build_verification_metrics import load_verification_campaigns


def build_report(
    campaigns: Iterable[VerificationCampaign],
    *,
    prefixes: tuple[int, ...] = (1, 2, 4, 8),
    comparisons: tuple[tuple[str, str], ...] = (),
    draws: int = 10_000,
    seed: int = 0,
    horizon_seconds: float = 3600.0,
    expected_input_hash: str | None = None,
    bundle_out: Path | None = None,
    model_tag: str | None = None,
) -> dict[str, object]:
    """Build metrics, analysis rows and paired effects without side effects."""

    rows = tuple(campaigns)
    model_tags = tuple(sorted({campaign.model_tag for campaign in rows}))
    if model_tag is not None:
        if not model_tag.strip():
            raise ValueError("model_tag must be non-empty")
        rows = tuple(campaign for campaign in rows if campaign.model_tag == model_tag)
        if not rows:
            raise ValueError(f"model_tag {model_tag!r} is absent from verification campaigns")
    elif len(model_tags) > 1:
        raise ValueError(
            "verification input contains multiple model_tag values; pass --model-tag to keep paired effects model-scoped"
        )
    normalized_prefixes = _normalize_prefixes(prefixes)
    _validate_comparisons(comparisons)
    metrics = compute_verification_metrics(rows, prefixes=normalized_prefixes)
    if expected_input_hash is not None and metrics.input_hash != expected_input_hash:
        raise ValueError(
            f"verification input hash mismatch: expected {expected_input_hash}, got {metrics.input_hash}"
        )
    methods = tuple(sorted({campaign.arm for campaign in rows}))
    by_prefix: dict[str, object] = {}
    bundle_manifests: list[dict[str, object]] = []
    for prefix in normalized_prefixes:
        outcomes = campaigns_to_analysis_outcomes(
            rows,
            prefix=prefix,
            horizon_seconds=horizon_seconds,
        )
        artifact = AnalysisArtifactBuilder().build(outcomes, draws=draws, seed=seed)
        if bundle_out is not None:
            manifest = artifact.write_bundle(Path(bundle_out) / f"prefix-{prefix}")
            bundle_manifests.append({
                "prefix": prefix,
                "path": manifest.name,
                "directory": f"prefix-{prefix}",
                "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "artifact_hash": artifact.artifact_hash,
            })
        paired: dict[str, object] = {}
        for left, right in comparisons:
            report = AnalysisArtifactBuilder().build(
                outcomes,
                compare_methods=(left, right),
                draws=draws,
                seed=seed,
            )
            name = f"{left}-minus-{right}"
            paired[name] = {
                "methods": [left, right],
                "artifact": report.as_dict(),
                "effects_by_lineage": {
                    key: list(values)
                    for key, values in report.report.paired_effects.items()
                },
            }
        by_prefix[str(prefix)] = {
            "row_count": len(outcomes),
            "analysis": artifact.as_dict(),
            "paired": paired,
        }
    body: dict[str, object] = {
        "schema_version": 1,
        "record_type": "paired_verification_analysis",
        "scope": "shared_verification_outcomes_only",
        "campaign_count": len(rows),
        "model_tag": rows[0].model_tag if rows and len({row.model_tag for row in rows}) == 1 else None,
        "methods": list(methods),
        "prefixes": list(normalized_prefixes),
        "comparisons": [list(pair) for pair in comparisons],
        "verification_metrics": metrics.as_dict(),
        "resource_metrics": build_resource_report(rows, comparisons=comparisons),
        "by_prefix": by_prefix,
        "provenance": {
            "horizon_seconds": float(horizon_seconds),
            "bootstrap_draws": draws,
            "seed": seed,
            "missingness_policy": "unavailable stages remain null and are counted separately",
            "verified_finding_policy": "all required shared stages plus property/security checks",
        },
    }
    if bundle_out is not None:
        body["bundle"] = {
            "manifests": bundle_manifests,
        }
    body["input_hash"] = metrics.input_hash
    body["report_hash"] = sha256_hex(body)
    return body


_RESOURCE_FIELDS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("proposal_input_tokens", ("proposal", "input_tokens"), "tokens"),
    ("proposal_output_tokens", ("proposal", "output_tokens"), "tokens"),
    ("proposal_request_seconds", ("proposal", "request_seconds"), "seconds"),
    ("provider_total_duration_seconds", ("proposal", "provider_total_duration_seconds"), "seconds"),
    ("total_stage_seconds", ("verification", "total_stage_seconds"), "seconds"),
    ("wall_seconds", ("wall_seconds",), "seconds"),
)


def build_resource_report(
    campaigns: Iterable[VerificationCampaign],
    *,
    comparisons: tuple[tuple[str, str], ...] = (),
) -> dict[str, object]:
    """Summarize tokens/timing separately from verification endpoints.

    Values are campaign-level aggregates from the archived timing contract.
    A numeric paired effect is emitted only when both matched campaigns have a
    complete observation for that resource; unavailable and T0 not-applicable
    observations are retained in method denominators and never imputed.
    """

    rows = tuple(campaigns)
    by_method: dict[str, dict[str, dict[str, object]]] = {}
    matched: dict[tuple[str, str, int], dict[str, dict[str, float]]] = {}
    for campaign in rows:
        method = campaign.arm
        method_summary = by_method.setdefault(method, {})
        for field, path, unit in _RESOURCE_FIELDS:
            observation = _timing_observation(campaign.timing, path)
            bucket = method_summary.setdefault(field, {
                "value": 0.0,
                "known": 0,
                "total": 0,
                "missing": 0,
                "unit": unit,
            })
            if observation is None:
                bucket["total"] += 1
                bucket["missing"] += 1
                bucket["value"] = None
                continue
            total = _nonnegative_int(observation.get("total"), 0)
            known = _nonnegative_int(observation.get("known"), 0)
            missing = _nonnegative_int(observation.get("missing"), max(0, total - known))
            if total == 0:
                continue
            bucket["total"] += total
            bucket["known"] += known
            bucket["missing"] += missing
            value = observation.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool) and missing == 0:
                if bucket["value"] is not None:
                    bucket["value"] += float(value)
            else:
                bucket["value"] = None
            if isinstance(value, (int, float)) and not isinstance(value, bool) and missing == 0:
                matched.setdefault(campaign.pair_key, {}).setdefault(method, {})[field] = float(value)

    for method_summary in by_method.values():
        for bucket in method_summary.values():
            bucket["note"] = "not_applicable" if bucket["total"] == 0 else ("missing_observation" if bucket["missing"] else None)
            if bucket["total"] == 0:
                bucket["value"] = None
    paired: dict[str, object] = {}
    for left, right in comparisons:
        contrast = f"{left}-minus-{right}"
        field_effects: dict[str, object] = {}
        for field, _path, unit in _RESOURCE_FIELDS:
            by_instance: dict[tuple[str, str], list[float]] = {}
            for pair_key, arms in matched.items():
                left_values = arms.get(left, {})
                right_values = arms.get(right, {})
                if field not in left_values or field not in right_values:
                    continue
                key = (pair_key.lineage_id, pair_key.instance_id)
                by_instance.setdefault(key, []).append(left_values[field] - right_values[field])
            by_lineage: dict[str, list[float]] = {}
            for (lineage, _instance), values in sorted(by_instance.items()):
                by_lineage.setdefault(lineage, []).append(mean(values))
            field_effects[field] = {
                "unit": unit,
                "lineage_effects": {
                    lineage: mean(values)
                    for lineage, values in sorted(by_lineage.items())
                },
                "known_lineages": len(by_lineage),
            }
        paired[contrast] = field_effects
    return {
        "by_method": {
            method: {field: dict(value) for field, value in sorted(summary.items())}
            for method, summary in sorted(by_method.items())
        },
        "paired_effects": paired,
        "definitions": {
            "tokens": "provider-reported prompt_tokens/eval_count projections only",
            "proposal_request_seconds": "archived transport elapsed_seconds, including retries",
            "provider_total_duration_seconds": "Ollama total_duration nanoseconds converted to seconds",
            "total_stage_seconds": "sum of shared StageResult elapsed_seconds, not wall-clock time",
            "wall_seconds": "caller-supplied campaign wall-clock time; never inferred",
        },
    }


def _timing_observation(timing: Mapping[str, Any] | None, path: tuple[str, ...]) -> Mapping[str, Any] | None:
    if not isinstance(timing, Mapping) or timing.get("status") == "unavailable":
        return None
    value: object = timing
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value if isinstance(value, Mapping) else None


def _nonnegative_int(value: object, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return default


def write_report(report: Mapping[str, object], path: Path) -> None:
    """Atomically write a canonical JSON report."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="verification_campaign JSONL")
    parser.add_argument("--out", type=Path, required=True, help="analysis report JSON output")
    parser.add_argument("--prefixes", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument(
        "--compare",
        nargs=2,
        action="append",
        default=[],
        metavar=("LEFT", "RIGHT"),
        help="paired method contrast; repeat for multiple contrasts",
    )
    parser.add_argument("--draws", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--horizon-seconds", type=float, default=3600.0)
    parser.add_argument("--expected-input-hash", default=None, help="abort unless the frozen verification input has this SHA-256")
    parser.add_argument("--bundle-out", type=Path, default=None, help="optional directory for per-prefix analysis bundles")
    parser.add_argument("--model-tag", default=None, help="select one model tag when the input contains multiple models")
    args = parser.parse_args(argv)
    campaigns = load_verification_campaigns(args.input)
    report = build_report(
        campaigns,
        prefixes=tuple(args.prefixes),
        comparisons=tuple(tuple(pair) for pair in args.compare),
        draws=args.draws,
        seed=args.seed,
        horizon_seconds=args.horizon_seconds,
        expected_input_hash=args.expected_input_hash,
        bundle_out=args.bundle_out,
        model_tag=args.model_tag,
    )
    write_report(report, args.out)
    print(json.dumps({
        "campaigns": report["campaign_count"],
        "prefixes": report["prefixes"],
        "methods": report["methods"],
        "input_hash": report["input_hash"],
        "report_hash": report["report_hash"],
    }, sort_keys=True))
    return 0


def _normalize_prefixes(prefixes: tuple[int, ...]) -> tuple[int, ...]:
    if not prefixes or any(isinstance(prefix, bool) or not isinstance(prefix, int) or prefix <= 0 for prefix in prefixes):
        raise ValueError("prefixes must contain positive integers")
    normalized = tuple(sorted(set(prefixes)))
    return normalized


def _validate_comparisons(comparisons: tuple[tuple[str, str], ...]) -> None:
    for pair in comparisons:
        if len(pair) != 2 or any(not isinstance(method, str) or not method.strip() for method in pair):
            raise ValueError("comparisons must contain two non-empty method names")
        if pair[0] == pair[1]:
            raise ValueError("comparison methods must be different")


if __name__ == "__main__":
    raise SystemExit(main())
