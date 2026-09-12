import unittest
from types import SimpleNamespace

from crossllm.verification import CandidateInput, PairKey, StageResult, StageStatus, VerificationOutcome
from scripts.run_verification_stage import (
    campaign_envelope,
    classify_campaign_availability,
    normalize_ground_truth,
    unavailable_outcome,
)
from crossllm.verification import CampaignAvailability


class VerificationStageRunnerTests(unittest.TestCase):
    def _candidate(self, status: str = "candidate") -> CandidateInput:
        return CandidateInput(
            campaign_id="campaign",
            attempt_id="attempt",
            pair_key=PairKey("lineage", "instance", 1),
            arm="crossllm",
            slot_index=0,
            slot_id="attempt:slot:0",
            proposal_status=status,
            canonical_ast_hash=None,
            raw_response_hash=None,
            candidate={"kind": "invariant", "body": {"kind": "literal", "type": "bool", "value": True}} if status == "candidate" else None,
            raw_response={},
        )

    def test_unavailable_candidate_keeps_downstream_non_applicable(self) -> None:
        outcome = unavailable_outcome(self._candidate(), "missing_runtime")
        self.assertEqual(outcome.stage_status("grounding"), StageStatus.UNSUPPORTED)
        self.assertEqual(outcome.stage_status("symbolic_search"), StageStatus.NOT_APPLICABLE)
        self.assertIsNone(outcome.verified_finding)

    def test_campaign_envelope_contains_candidate_and_outcome_for_resume(self) -> None:
        candidate = self._candidate()
        outcome = VerificationOutcome(
            candidate=candidate,
            stages=(
                StageResult("grounding", StageStatus.PASSED),
                StageResult("symbolic_search", StageStatus.UNSUPPORTED, "executor_missing"),
                StageResult("witness_check", StageStatus.NOT_APPLICABLE, "symbolic_search_not_passed"),
                StageResult("independent_replay", StageStatus.NOT_APPLICABLE, "symbolic_search_not_passed"),
            ),
        )
        archive = SimpleNamespace(
            campaign_id="campaign", attempt_id="attempt", arm="crossllm", method="X", backbone="gpt-oss",
            model_tag="gpt-oss", pair_key=PairKey("lineage", "instance", 1), slot_count=8, archive_path="archive.jsonl",
        )
        row = campaign_envelope(archive, "positive", "logic", CampaignAvailability.UNSUPPORTED, "backend_missing", [outcome])
        self.assertEqual(row["slot_count"], 8)
        self.assertEqual(row["outcomes"][0]["candidate"]["slot_index"], 0)
        self.assertEqual(row["outcomes"][0]["outcome"]["stages"][1]["status"], "unsupported")

    def test_availability_preserves_provider_and_stage_missingness(self) -> None:
        archive = SimpleNamespace(provider_failure_count=1)
        outcome = unavailable_outcome(self._candidate(), "missing_runtime")
        availability, reason = classify_campaign_availability(archive, [outcome], object())
        self.assertEqual(availability, CampaignAvailability.UNKNOWN)
        self.assertEqual(reason, "provider_failure_or_partial_archive")

    def test_public_truth_aliases_are_normalized(self) -> None:
        self.assertEqual(normalize_ground_truth("vulnerable"), "positive")
        self.assertEqual(normalize_ground_truth("patched"), "negative")
        with self.assertRaises(ValueError):
            normalize_ground_truth("unknown-status")


if __name__ == "__main__":
    unittest.main()
