import unittest

from crossllm.verification import CandidateInput, PairKey, StageResult, StageStatus, VerificationOutcome


class VerificationRecordTests(unittest.TestCase):
    def _candidate(self) -> CandidateInput:
        return CandidateInput(
            campaign_id="c",
            attempt_id="a",
            pair_key=PairKey("l", "i", 1),
            arm="crossllm",
            slot_index=0,
            slot_id="s",
            proposal_status="candidate",
            canonical_ast_hash=None,
            raw_response_hash=None,
            candidate={"kind": "invariant", "body": {"kind": "literal", "type": "bool", "value": True}},
            raw_response={},
        )

    def _stages(self) -> tuple[StageResult, ...]:
        return tuple(StageResult(name, StageStatus.PASSED) for name in (
            "grounding", "symbolic_search", "witness_check", "independent_replay",
        ))

    def test_verified_finding_uses_false_property_holds(self) -> None:
        outcome = VerificationOutcome(
            self._candidate(), self._stages(),
            candidate_violation=True, property_holds=False,
            security_relevance=True, verified_finding=True,
        )
        self.assertTrue(outcome.verified_finding)

    def test_verified_finding_rejects_true_property_holds(self) -> None:
        with self.assertRaisesRegex(ValueError, "property_holds=false"):
            VerificationOutcome(
                self._candidate(), self._stages(),
                candidate_violation=True, property_holds=True,
                security_relevance=True, verified_finding=True,
            )


if __name__ == "__main__":
    unittest.main()
