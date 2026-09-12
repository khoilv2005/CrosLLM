#!/usr/bin/env python3
"""Exercise the final gpt-oss statistics path without fabricating verification.

It converts the verification queue into one explicit *unknown* outcome per
campaign, then invokes the repository's hierarchical/paired analysis builder.
The generated bundle validates identifiers, arm pairing, lineage aggregation,
bootstrap and Holm plumbing while leaving all verification endpoints unknown.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from crossllm.analysis import AnalysisArtifactBuilder


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    campaigns: dict[str, dict[str, object]] = {}
    for number, line in enumerate(args.queue.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        campaign_id = row.get("campaign_id")
        if not isinstance(campaign_id, str):
            raise ValueError(f"queue line {number}: campaign_id is missing")
        if campaign_id not in campaigns:
            truth = row.get("ground_truth")
            campaigns[campaign_id] = {
                "campaign_id": campaign_id,
                "instance_id": row["instance_id"],
                "lineage_id": row["lineage_id"],
                "method": row["arm"],
                "replicate": row["replicate"],
                "ground_truth": "positive" if truth == "vulnerable" else "negative" if truth == "patched" else "unresolved",
                "availability": "unknown",
                "first_failure": "source_backed_verification_executor_missing",
                "detected": None,
                "useful_proposal": None,
                "claim_emitted": None,
                "correct_claim": None,
                "native_witness": None,
                "independent_replay": None,
            }
    outcomes = [campaigns[key] for key in sorted(campaigns)]
    _write_jsonl(args.out / "verification_outcomes_pending.jsonl", outcomes)
    artifact = AnalysisArtifactBuilder().build(outcomes, draws=1000, seed=20260912)
    artifact.write_bundle(args.out / "analysis_bundle")
    summary = {
        "record_type": "gptoss_statistics_dry_run",
        "campaign_outcomes": len(outcomes),
        "verification_outcomes_materialized": 0,
        "missingness_policy": "unverified endpoints remain null/unknown and are excluded from effect estimates",
        "paired_crossllm_direct": "validated structurally; no verified effects available",
        "lineage_bootstrap": "executed with empty verified contrast family",
        "holm": "wired through AnalysisArtifactBuilder; no non-null verified hypotheses yet",
        "token_latency_effect": "separate proposal/stage timing exporter is available; this dry-run intentionally does not synthesize values",
        "analysis_artifact_hash": artifact.artifact_hash,
    }
    (args.out / "dry_run_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"campaign_outcomes": len(outcomes), "artifact_hash": artifact.artifact_hash}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
