import unittest
from dataclasses import replace

from crossllm.methods import T0DeterministicProposer, T0Template, T0TemplateLibrary
from crossllm.semantics import Message, PairedFixture
from crossllm.verification import (
    FixtureVerificationConfig,
    FixtureVerificationExecutors,
    PairKey,
    StageResult,
    StageStatus,
    verify_method_run,
)
from crossllm.verification.adapter import public_xlir_symbols
from crossllm.verification.runtime import load_case_runtime

from tests.unit.test_runtime_binding import RuntimeBindingTests


class VerificationRunnerTests(unittest.TestCase):
    def test_t0_uses_the_same_verification_pipeline_as_provider_methods(self) -> None:
        helper = RuntimeBindingTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        root, lineage = helper._fixture()
        case = replace(load_case_runtime(root, lineage, "eval_fixture_mut_01"), missing_fields=())
        symbols = public_xlir_symbols(root, lineage)
        pack = {
            "public_files": {
                "storage_symbols.json": {
                    "symbols": [symbol.as_dict() for symbol in symbols],
                },
            },
            "gold_access": "disabled",
        }
        library = T0TemplateLibrary(
            "t0-runner-test-v1",
            8,
            (T0Template("state-stability", "invariant", "eq", "pre", "post", "sorted_public_scalar_storage_symbols"),),
        )
        method_run = T0DeterministicProposer(library).propose(pack, attempt_id="t0-attempt").method_run
        backend = FixtureVerificationExecutors(FixtureVerificationConfig(
            fixture=PairedFixture(),
            messages=(Message("source", "destination", "bridge", "receiver", 1, "commit-1"),),
            state_readers={(
                "storage.Bridge.slot_0.flag", "pre", "source",
            ): lambda _state: False, (
                "storage.Bridge.slot_0.flag", "post", "source",
            ): lambda state: state.transaction_count > 0},
        ), independent_replay=lambda _plan, witness: StageResult(
            "independent_replay", StageStatus.PASSED,
            evidence={"security_relevance": True, "trace_hash": witness.trace_hash},
        ))

        outcomes = verify_method_run(
            method_run,
            campaign_id="t0-campaign",
            pair_key=PairKey(lineage, "eval_fixture_mut_01", 1),
            arm="t0",
            case=case,
            symbols=symbols,
            executors=backend.executors(),
        )

        self.assertEqual(len(outcomes), 8)
        self.assertTrue(outcomes[0].verified_finding)
        self.assertEqual(outcomes[0].stage_status("symbolic_search"), StageStatus.PASSED)
        self.assertEqual(outcomes[0].stage_status("witness_check"), StageStatus.PASSED)
        self.assertEqual(outcomes[0].stage_status("independent_replay"), StageStatus.PASSED)
        self.assertIsNone(outcomes[1].verified_finding)
        self.assertEqual(outcomes[1].stage_status("grounding"), StageStatus.NOT_APPLICABLE)


if __name__ == "__main__":
    unittest.main()
