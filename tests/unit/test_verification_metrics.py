import unittest
from pathlib import Path
import tempfile
import json

from crossllm.verification import (
    CampaignAvailability,
    CandidateInput,
    PairKey,
    StageResult,
    StageStatus,
    VerificationCampaign,
    VerificationOutcome,
    compute_verification_metrics,
)
from scripts.build_verification_metrics import load_verification_campaigns


def _candidate(campaign_id: str, arm: str, pair: PairKey, slot: int) -> CandidateInput:
    return CandidateInput(
        campaign_id=campaign_id,
        attempt_id=f"{campaign_id}-attempt",
        pair_key=pair,
        arm=arm,
        slot_index=slot,
        slot_id=f"{campaign_id}:slot:{slot}",
        proposal_status="candidate",
        canonical_ast_hash=None,
        raw_response_hash=None,
        candidate={"kind": "invariant", "body": {"kind": "literal", "type": "bool", "value": True}},
        raw_response={},
    )


def _outcome(candidate: CandidateInput, verified: bool | None, *, timeout: bool = False) -> VerificationOutcome:
    statuses = (
        StageResult("grounding", StageStatus.PASSED),
        StageResult("symbolic_search", StageStatus.TIMEOUT if timeout else StageStatus.PASSED),
        StageResult("witness_check", StageStatus.NOT_APPLICABLE if timeout else StageStatus.PASSED),
        StageResult("independent_replay", StageStatus.NOT_APPLICABLE if timeout else StageStatus.PASSED),
    )
    return VerificationOutcome(
        candidate=candidate,
        stages=statuses,
        candidate_violation=True if verified else None,
        property_holds=False if verified else None,
        security_relevance=True if verified else None,
        verified_finding=verified,
        first_failure="symbolic_search" if timeout else None,
    )


class VerificationMetricsTests(unittest.TestCase):
    def test_prefix_recall_and_negative_controls_keep_known_denominators_separate(self) -> None:
        positive_key = PairKey("l1", "i1", 1)
        negative_key = PairKey("l1", "i2", 1)
        positive = VerificationCampaign(
            "pos", "crossllm", positive_key, "positive", 8,
            (_outcome(_candidate("pos", "crossllm", positive_key, 3), True),),
            model_tag="gpt-oss", property_family="replay",
        )
        negative = VerificationCampaign(
            "neg", "crossllm", negative_key, "negative", 8,
            (_outcome(_candidate("neg", "crossllm", negative_key, 0), True),),
            model_tag="gpt-oss", property_family="replay",
        )
        metrics = compute_verification_metrics((positive, negative))
        group = "crossllm|gpt-oss|replay"
        self.assertEqual(metrics.verified_recall[group][4].hits, 1)
        self.assertEqual(metrics.verified_recall[group][1].hits, 0)
        self.assertEqual(metrics.false_alert_rate[group].value, 1.0)
        self.assertEqual(metrics.false_discovery_proportion[group].value, 0.5)

    def test_unknown_campaign_is_not_counted_as_no_alert(self) -> None:
        pair = PairKey("l1", "i1", 1)
        row = VerificationCampaign(
            "unknown", "direct", pair, "negative", 8, (),
            availability=CampaignAvailability.UNKNOWN,
            missing_reason="provider_response_uncertain",
            model_tag="gpt-oss", property_family="logic",
        )
        metrics = compute_verification_metrics((row,))
        metric = metrics.false_alert_rate["direct|gpt-oss|logic"]
        self.assertIsNone(metric.value)
        self.assertEqual(metric.known, 0)
        self.assertEqual(metric.missing, 1)

    def test_paired_effects_are_aggregated_by_lineage(self) -> None:
        pair = PairKey("l1", "i1", 1)
        cross = VerificationCampaign(
            "x", "crossllm", pair, "positive", 8,
            (_outcome(_candidate("x", "crossllm", pair, 0), True),),
            model_tag="gpt-oss", property_family="logic",
        )
        direct = VerificationCampaign(
            "d", "direct", pair, "positive", 8,
            (_outcome(_candidate("d", "direct", pair, 0), False),),
            model_tag="gpt-oss", property_family="logic",
        )
        metrics = compute_verification_metrics((direct, cross), paired_contrasts=(("crossllm", "direct"),))
        self.assertEqual(metrics.paired_effects["crossllm-minus-direct"]["1"], (1.0,))

    def test_requested_prefix_cannot_exceed_campaign_slots(self) -> None:
        pair = PairKey("l1", "i1", 1)
        row = VerificationCampaign("short", "t0", pair, "positive", 4, ())
        with self.assertRaisesRegex(ValueError, "smaller than a requested prefix"):
            compute_verification_metrics((row,))

    def test_jsonl_loader_requires_explicit_campaign_availability_and_restores_outcomes(self) -> None:
        pair = PairKey("l1", "i1", 1)
        candidate = _candidate("json", "crossllm", pair, 0)
        outcome = _outcome(candidate, True)
        payload = {
            "record_type": "verification_campaign",
            "campaign_id": "json",
            "arm": "crossllm",
            "model_tag": "gpt-oss",
            "property_family": "logic",
            "lineage_id": "l1",
            "instance_id": "i1",
            "replicate": 1,
            "ground_truth": "vulnerable",
            "slot_count": 8,
            "availability": "available",
            "outcomes": [{
                "candidate": {
                    "campaign_id": candidate.campaign_id,
                    "attempt_id": candidate.attempt_id,
                    "lineage_id": pair.lineage_id,
                    "instance_id": pair.instance_id,
                    "replicate": pair.replicate,
                    "arm": candidate.arm,
                    "slot_index": candidate.slot_index,
                    "slot_id": candidate.slot_id,
                    "proposal_status": candidate.proposal_status,
                    "canonical_ast_hash": candidate.canonical_ast_hash,
                    "raw_response_hash": candidate.raw_response_hash,
                    "candidate": candidate.candidate,
                    "raw_response": {},
                },
                "outcome": outcome.as_dict(),
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outcomes.jsonl"
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            rows = load_verification_campaigns(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ground_truth, "positive")
        self.assertTrue(rows[0].outcomes[0].verified_finding)


if __name__ == "__main__":
    unittest.main()
