import unittest

from crossllm.analysis import OutcomeAvailability, campaigns_to_analysis_outcomes
from crossllm.verification import (
    CampaignAvailability,
    CandidateInput,
    PairKey,
    StageResult,
    StageStatus,
    VerificationCampaign,
    VerificationOutcome,
)


def _campaign(campaign_id: str, arm: str, availability: CampaignAvailability = CampaignAvailability.AVAILABLE) -> VerificationCampaign:
    pair = PairKey("lineage", campaign_id, 1)
    candidate = CandidateInput(
        campaign_id=campaign_id,
        attempt_id="attempt",
        pair_key=pair,
        arm=arm,
        slot_index=0,
        slot_id="slot:0",
        proposal_status="candidate",
        canonical_ast_hash=None,
        raw_response_hash=None,
        candidate={"kind": "invariant"},
        raw_response={},
    )
    outcome = VerificationOutcome(
        candidate=candidate,
        stages=(
            StageResult("grounding", StageStatus.PASSED),
            StageResult("symbolic_search", StageStatus.PASSED, elapsed_seconds=1.0),
            StageResult("witness_check", StageStatus.PASSED, elapsed_seconds=2.0),
            StageResult("independent_replay", StageStatus.PASSED, elapsed_seconds=3.0),
        ),
        candidate_violation=True,
        property_holds=False,
        security_relevance=True,
        verified_finding=True,
    )
    return VerificationCampaign(
        campaign_id=campaign_id,
        arm=arm,
        pair_key=pair,
        ground_truth="positive",
        slot_count=8,
        outcomes=(outcome,),
        availability=availability,
        missing_reason="runtime_or_backend_unsupported" if availability is not CampaignAvailability.AVAILABLE else None,
    )


class AnalysisVerificationBridgeTests(unittest.TestCase):
    def test_projects_verified_pipeline_outcome_and_times(self) -> None:
        row = campaigns_to_analysis_outcomes((_campaign("campaign", "crossllm"),))[0]
        self.assertEqual(row.availability, OutcomeAvailability.AVAILABLE)
        self.assertTrue(row.detected)
        self.assertTrue(row.useful_proposal)
        self.assertTrue(row.native_witness)
        self.assertTrue(row.independent_replay)
        self.assertEqual(row.witness_time_seconds, 2.0)
        self.assertEqual(row.claim_time_seconds, 6.0)

    def test_unavailable_campaign_does_not_become_a_false_negative(self) -> None:
        row = campaigns_to_analysis_outcomes((_campaign("unsupported", "direct", CampaignAvailability.UNSUPPORTED),))[0]
        self.assertEqual(row.availability, OutcomeAvailability.UNSUPPORTED)
        self.assertIsNone(row.detected)
        self.assertTrue(row.native_witness)
        self.assertEqual(row.first_failure, "runtime_or_backend_unsupported")


if __name__ == "__main__":
    unittest.main()
