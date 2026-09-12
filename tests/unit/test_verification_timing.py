import unittest

from crossllm.methods import MethodRun, MethodTrack, ProposalSlot, ProposalSlotStatus
from crossllm.providers import ProviderResponse
from crossllm.verification import (
    CampaignArchive,
    CandidateInput,
    PairKey,
    StageResult,
    StageStatus,
    VerificationOutcome,
    summarize_method_timing,
    summarize_campaign_archive_timing,
)


class VerificationTimingTests(unittest.TestCase):
    def _candidate(self, slot: int) -> CandidateInput:
        return CandidateInput(
            campaign_id="campaign",
            attempt_id="attempt",
            pair_key=PairKey("lineage", "instance", 1),
            arm="crossllm",
            slot_index=slot,
            slot_id=f"attempt:slot:{slot}",
            proposal_status="candidate",
            canonical_ast_hash=None,
            raw_response_hash=None,
            candidate={"kind": "invariant"},
            raw_response={},
        )

    def test_provider_timing_and_stage_timing_are_separate(self) -> None:
        slots = tuple(
            ProposalSlot(f"attempt:slot:{index}", index, ProposalSlotStatus.CANDIDATE, candidate={"kind": "invariant"})
            for index in range(2)
        )
        responses = tuple(ProviderResponse(
            request_hash=f"{index + 1:064x}", response_hash=f"{index + 10:064x}", http_status=200,
            response_text="{}", response_model="served", finish_reason="stop",
            usage={"prompt_tokens": 11 + index, "generated_tokens": 5 + index}, attempts=1,
            partial=False, elapsed_seconds=0.5 + index,
            ollama={"total_duration": 1_000_000_000 * (2 + index)},
        ) for index in range(2))
        method_run = MethodRun(
            MethodTrack.CROSSLLM, "glm", "attempt", "a" * 64, "b" * 64,
            {"temperature": 0.6}, slots, responses,
        )
        outcomes = tuple(VerificationOutcome(
            candidate=self._candidate(index),
            stages=(
                StageResult("grounding", StageStatus.PASSED, elapsed_seconds=0.1),
                StageResult("symbolic_search", StageStatus.PASSED, elapsed_seconds=1.0 + index),
                StageResult("witness_check", StageStatus.PASSED, elapsed_seconds=2.0),
                StageResult("independent_replay", StageStatus.PASSED, elapsed_seconds=3.0),
            ),
        ) for index in range(2))
        timing = summarize_method_timing(method_run, outcomes, wall_seconds=12.0)
        self.assertEqual(timing.proposal_input_tokens.value, 23.0)
        self.assertEqual(timing.proposal_output_tokens.value, 11.0)
        self.assertEqual(timing.proposal_request_seconds.value, 2.0)
        self.assertEqual(timing.provider_total_duration_seconds.value, 5.0)
        self.assertEqual(timing.stage_seconds["symbolic_search"].value, 3.0)
        self.assertEqual(timing.total_stage_seconds.value, 13.2)
        self.assertEqual(timing.wall_seconds.value, 12.0)

    def test_t0_has_not_applicable_provider_tokens_and_missing_wall_time(self) -> None:
        slots = tuple(
            ProposalSlot(f"t0:slot:{index}", index, ProposalSlotStatus.ABSTAIN)
            for index in range(2)
        )
        method_run = MethodRun(
            MethodTrack.T0, "deterministic", "t0", "a" * 64, "b" * 64,
            {}, slots,
        )
        timing = summarize_method_timing(method_run)
        self.assertIsNone(timing.proposal_input_tokens.value)
        self.assertEqual(timing.proposal_input_tokens.total, 0)
        self.assertEqual(timing.proposal_input_tokens.note, "no_provider_calls_t0")
        self.assertIsNone(timing.wall_seconds.value)
        self.assertEqual(timing.wall_seconds.missing, 1)

    def test_archive_bridge_preserves_providerless_t0(self) -> None:
        archive = CampaignArchive(
            campaign_id="t0-campaign",
            attempt_id="t0-attempt",
            pair_key=PairKey("lineage", "instance", 1),
            arm="t0",
            method="t0",
            backbone="deterministic",
            model_tag="deterministic",
            config_hash="c" * 64,
            request_settings_hash="d" * 64,
            artifact_pack_hash="e" * 64,
            slots=tuple({"index": index, "status": "abstain"} for index in range(2)),
            provider_responses=(),
            budget_checks=(),
            raw_row={
                "method_run": {
                    "track": "T0",
                    "settings": {},
                    "slots": [{"index": 0}, {"index": 1}],
                    "provider_responses": [],
                },
            },
            archive_path="t0.jsonl",
        )
        timing = summarize_campaign_archive_timing(archive)
        self.assertEqual(timing.track, "T0")
        self.assertEqual(timing.proposal_input_tokens.note, "no_provider_calls_t0")


if __name__ == "__main__":
    unittest.main()
