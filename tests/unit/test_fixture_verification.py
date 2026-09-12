import unittest
from dataclasses import replace

from crossllm.semantics import Message, PairedFixture
from crossllm.verification import (
    FixtureVerificationConfig,
    FixtureVerificationExecutors,
    PairKey,
    SharedVerificationPipeline,
    StageResult,
    StageStatus,
)
from crossllm.verification.adapter import public_xlir_symbols
from crossllm.verification.records import CandidateInput
from crossllm.verification.runtime import load_case_runtime

from tests.unit.test_runtime_binding import RuntimeBindingTests


class FixtureVerificationTests(unittest.TestCase):
    def _case_and_candidate(self):
        helper = RuntimeBindingTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        root, lineage = helper._fixture()
        case = replace(load_case_runtime(root, lineage, "eval_fixture_mut_01"), missing_fields=())
        candidate = CandidateInput(
            campaign_id="campaign",
            attempt_id="attempt",
            pair_key=PairKey(lineage, "eval_fixture_mut_01", 1),
            arm="crossllm",
            slot_index=0,
            slot_id="attempt:slot:0",
            proposal_status="candidate",
            canonical_ast_hash=None,
            raw_response_hash=None,
            candidate={
                "kind": "invariant",
                "invariant_id": "flag-cleared-after-action",
                "body": {"kind": "binary", "operator": "eq",
                    "left": {"kind": "symbol", "symbol_id": "storage.Bridge.slot_0.flag", "state": "post"},
                    "right": {"kind": "literal", "type": "bool", "value": False}},
            },
            raw_response={},
        )
        return root, lineage, case, candidate

    def test_fixture_backend_produces_candidate_specific_witness_and_common_result(self) -> None:
        root, lineage, case, candidate = self._case_and_candidate()
        fixture = PairedFixture()
        message = Message("source", "destination", "bridge", "receiver", 1, "commit-1")
        backend = FixtureVerificationExecutors(FixtureVerificationConfig(
            fixture=fixture,
            messages=(message,),
            state_readers={(
                "storage.Bridge.slot_0.flag", "post", "source",
            ): lambda state: state.transaction_count > 0},
        ), independent_replay=lambda _plan, witness: StageResult(
            "independent_replay", StageStatus.PASSED,
            evidence={"security_relevance": True, "trace_hash": witness.trace_hash},
        ))
        outcome = SharedVerificationPipeline(
            case,
            public_xlir_symbols(root, lineage),
            executors=backend.executors(),
        ).verify(candidate)
        self.assertEqual(outcome.stage_status("symbolic_search"), StageStatus.PASSED)
        self.assertEqual(outcome.stage_status("witness_check"), StageStatus.PASSED)
        self.assertEqual(outcome.stage_status("independent_replay"), StageStatus.PASSED)
        self.assertTrue(outcome.candidate_violation)
        self.assertFalse(outcome.property_holds)
        self.assertTrue(outcome.verified_finding)

    def test_fixture_backend_marks_no_counterexample_without_witness(self) -> None:
        root, lineage, case, candidate = self._case_and_candidate()
        candidate = replace(candidate, candidate={
            "kind": "invariant",
            "invariant_id": "flag-always-true",
            "body": {"kind": "binary", "operator": "eq",
                "left": {"kind": "symbol", "symbol_id": "storage.Bridge.slot_0.flag", "state": "post"},
                "right": {"kind": "literal", "type": "bool", "value": True}},
        })
        backend = FixtureVerificationExecutors(FixtureVerificationConfig(
            fixture=PairedFixture(), messages=(Message("source", "destination", "bridge", "receiver", 1, "commit-1"),),
            state_readers={("storage.Bridge.slot_0.flag", "post", "source"): lambda _state: True},
        ))
        outcome = SharedVerificationPipeline(case, public_xlir_symbols(root, lineage), executors=backend.executors()).verify(candidate)
        self.assertEqual(outcome.stage_status("symbolic_search"), StageStatus.PASSED)
        self.assertFalse(outcome.candidate_violation)
        self.assertEqual(outcome.stage_status("witness_check"), StageStatus.NOT_APPLICABLE)
        self.assertIsNone(outcome.verified_finding)


if __name__ == "__main__":
    unittest.main()
