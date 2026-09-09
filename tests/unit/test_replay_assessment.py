from __future__ import annotations

import unittest

from crossllm.contracts.records import ReplayStatus
from crossllm.replay import WitnessAssessmentStatus, assess_witness


class ReplayAssessmentTests(unittest.TestCase):
    def test_confirmation_requires_all_independent_layers_and_keeps_times_separate(self) -> None:
        result = assess_witness(
            witness_id="wit-1",
            model_trace_valid=True,
            native_replay_status=ReplayStatus.PASS,
            independent_replay_status=ReplayStatus.PASS,
            security_relevance=True,
            allowed_capabilities=("local_state", "read_only_evm"),
            required_capabilities=("read_only_evm",),
            native_witness_seconds=1.25,
            evaluator_reproduction_seconds=2.5,
        )
        self.assertEqual(result.status, WitnessAssessmentStatus.CONFIRMED)
        self.assertTrue(result.confirmed)
        self.assertEqual(result.native_witness_seconds, 1.25)
        self.assertEqual(result.evaluator_reproduction_seconds, 2.5)

    def test_unknown_or_unsupported_evidence_stays_pending(self) -> None:
        result = assess_witness(
            witness_id="wit-2",
            model_trace_valid=True,
            native_replay_status=ReplayStatus.PASS,
            independent_replay_status=ReplayStatus.UNKNOWN,
            security_relevance=None,
        )
        self.assertEqual(result.status, WitnessAssessmentStatus.PENDING)
        self.assertIn("independent_replay_unknown", result.reasons)
        self.assertIn("security_relevance_unassessed", result.reasons)

    def test_hard_failures_and_capability_mismatch_reject(self) -> None:
        failed = assess_witness(
            witness_id="wit-3",
            model_trace_valid=True,
            native_replay_status=ReplayStatus.PASS,
            independent_replay_status=ReplayStatus.FAIL,
            security_relevance=True,
        )
        self.assertEqual(failed.status, WitnessAssessmentStatus.REJECTED)
        self.assertIn("independent_replay_failed", failed.reasons)
        invalid_model = assess_witness(
            witness_id="wit-3b",
            model_trace_valid=False,
            native_replay_status=ReplayStatus.PASS,
            independent_replay_status=ReplayStatus.PASS,
            security_relevance=True,
        )
        self.assertEqual(invalid_model.status, WitnessAssessmentStatus.REJECTED)
        with self.assertRaisesRegex(ValueError, "required capabilities"):
            assess_witness(
                witness_id="wit-4",
                model_trace_valid=True,
                native_replay_status=ReplayStatus.PASS,
                independent_replay_status=ReplayStatus.PASS,
                security_relevance=True,
                required_capabilities=("broadcast",),
                allowed_capabilities=("read_only_evm",),
            )


if __name__ == "__main__":
    unittest.main()
