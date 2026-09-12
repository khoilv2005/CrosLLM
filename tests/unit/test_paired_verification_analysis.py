from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from crossllm.analysis import campaigns_to_analysis_outcomes
from crossllm.verification import (
    CampaignAvailability,
    CandidateInput,
    PairKey,
    StageResult,
    StageStatus,
    VerificationCampaign,
    VerificationOutcome,
)
from scripts.build_paired_verification_analysis import build_report, main


def _outcome(campaign_id: str, arm: str, pair: PairKey, *, detected: bool | None) -> VerificationOutcome:
    candidate = CandidateInput(
        campaign_id=campaign_id,
        attempt_id=f"attempt-{campaign_id}",
        pair_key=pair,
        arm=arm,
        slot_index=0,
        slot_id=f"{campaign_id}:slot:0",
        proposal_status="candidate",
        canonical_ast_hash=None,
        raw_response_hash=None,
        candidate={"kind": "invariant", "body": {}},
        raw_response={},
    )
    stages = (
        StageResult("grounding", StageStatus.PASSED),
        StageResult("symbolic_search", StageStatus.PASSED, evidence={"candidate_violation": detected}),
        StageResult("witness_check", StageStatus.PASSED, evidence={"property_holds": not detected}),
        StageResult("independent_replay", StageStatus.PASSED, evidence={"security_relevance": detected}),
    )
    verified = detected if detected is not None else None
    return VerificationOutcome(
        candidate=candidate,
        stages=stages,
        candidate_violation=detected,
        property_holds=(not detected) if detected is not None else None,
        security_relevance=detected,
        verified_finding=verified,
    )


def _campaign(campaign_id: str, arm: str, instance: str, lineage: str, replicate: int, detected: bool | None) -> VerificationCampaign:
    pair = PairKey(lineage, instance, replicate)
    return VerificationCampaign(
        campaign_id=campaign_id,
        arm=arm,
        pair_key=pair,
        ground_truth="positive",
        slot_count=8,
        outcomes=(_outcome(campaign_id, arm, pair, detected=detected),),
        availability=(CampaignAvailability.AVAILABLE if detected is not None else CampaignAvailability.UNKNOWN),
        missing_reason=None if detected is not None else "verification_stage_incomplete",
        model_tag="test-model",
        property_family="logic",
    )


class PairedVerificationAnalysisTests(unittest.TestCase):
    def campaigns(self) -> tuple[VerificationCampaign, ...]:
        return (
            _campaign("x-a-i1-r1", "crossllm", "i1", "a", 1, True),
            _campaign("d-a-i1-r1", "direct", "i1", "a", 1, False),
            _campaign("t-a-i1-r1", "t0", "i1", "a", 1, None),
            _campaign("x-b-i2-r1", "crossllm", "i2", "b", 1, False),
            _campaign("d-b-i2-r1", "direct", "i2", "b", 1, False),
        )

    def test_report_keeps_missingness_and_emits_multiple_paired_prefixes(self) -> None:
        report = build_report(
            self.campaigns(),
            prefixes=(1, 2, 1),
            comparisons=(("crossllm", "direct"), ("crossllm", "t0")),
            draws=25,
            seed=7,
        )
        self.assertEqual(report["prefixes"], [1, 2])
        self.assertEqual(report["input_hash"], report["verification_metrics"]["input_hash"])
        prefix = report["by_prefix"]["1"]
        self.assertIn("crossllm-minus-direct", prefix["paired"])
        self.assertIn("crossllm-minus-t0", prefix["paired"])
        self.assertEqual(
            prefix["paired"]["crossllm-minus-direct"]["effects_by_lineage"]["crossllm-minus-direct"],
            [1.0, 0.0],
        )
        outcomes = campaigns_to_analysis_outcomes(self.campaigns(), prefix=1)
        t0 = next(row for row in outcomes if row.method == "t0")
        self.assertIsNone(t0.detected)
        self.assertEqual(t0.availability.value, "unknown")

    def test_cli_writes_hash_bound_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "campaigns.jsonl"
            # Use the in-memory contract's JSON shape to exercise the strict
            # loader as well as the report writer.
            rows: list[dict[str, object]] = []
            for campaign in self.campaigns():
                rows.append({
                    "record_type": "verification_campaign",
                    "campaign_id": campaign.campaign_id,
                    "lineage_id": campaign.pair_key.lineage_id,
                    "instance_id": campaign.pair_key.instance_id,
                    "arm": campaign.arm,
                    "replicate": campaign.pair_key.replicate,
                    "ground_truth": campaign.ground_truth,
                    "slot_count": campaign.slot_count,
                    "availability": campaign.availability.value,
                    "missing_reason": campaign.missing_reason,
                    "model_tag": campaign.model_tag,
                    "property_family": campaign.property_family,
                    "outcomes": [{"candidate": {
                        "campaign_id": campaign.campaign_id,
                        "attempt_id": outcome.candidate.attempt_id,
                        "lineage_id": campaign.pair_key.lineage_id,
                        "instance_id": campaign.pair_key.instance_id,
                        "replicate": campaign.pair_key.replicate,
                        "arm": campaign.arm,
                        "slot_index": 0,
                        "slot_id": outcome.candidate.slot_id,
                        "proposal_status": "candidate",
                        "canonical_ast_hash": None,
                        "raw_response_hash": None,
                        "candidate": outcome.candidate.candidate,
                        "raw_response": {},
                    }, "outcome": outcome.as_dict()} for outcome in campaign.outcomes],
                })
            source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            output = root / "analysis.json"
            self.assertEqual(main([
                "--input", str(source), "--out", str(output), "--compare", "crossllm", "direct", "--draws", "5",
            ]), 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["record_type"], "paired_verification_analysis")
            self.assertEqual(len(payload["report_hash"]), 64)
            self.assertEqual(payload["campaign_count"], len(rows))


if __name__ == "__main__":
    unittest.main()
