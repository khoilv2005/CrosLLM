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
import json
from pathlib import Path
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
) -> dict[str, object]:
    """Build metrics, analysis rows and paired effects without side effects."""

    rows = tuple(campaigns)
    normalized_prefixes = _normalize_prefixes(prefixes)
    _validate_comparisons(comparisons)
    metrics = compute_verification_metrics(rows, prefixes=normalized_prefixes)
    methods = tuple(sorted({campaign.arm for campaign in rows}))
    by_prefix: dict[str, object] = {}
    for prefix in normalized_prefixes:
        outcomes = campaigns_to_analysis_outcomes(
            rows,
            prefix=prefix,
            horizon_seconds=horizon_seconds,
        )
        artifact = AnalysisArtifactBuilder().build(outcomes, draws=draws, seed=seed)
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
        "methods": list(methods),
        "prefixes": list(normalized_prefixes),
        "comparisons": [list(pair) for pair in comparisons],
        "verification_metrics": metrics.as_dict(),
        "by_prefix": by_prefix,
        "provenance": {
            "horizon_seconds": float(horizon_seconds),
            "bootstrap_draws": draws,
            "seed": seed,
            "missingness_policy": "unavailable stages remain null and are counted separately",
            "verified_finding_policy": "all required shared stages plus property/security checks",
        },
    }
    body["input_hash"] = metrics.input_hash
    body["report_hash"] = sha256_hex(body)
    return body


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
    args = parser.parse_args(argv)
    campaigns = load_verification_campaigns(args.input)
    report = build_report(
        campaigns,
        prefixes=tuple(args.prefixes),
        comparisons=tuple(tuple(pair) for pair in args.compare),
        draws=args.draws,
        seed=args.seed,
        horizon_seconds=args.horizon_seconds,
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
