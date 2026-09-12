import unittest

from crossllm.methods import MethodTrack, T0DeterministicProposer, T0Template, T0TemplateLibrary
from crossllm.verification import PairKey, candidates_from_method_run


class VerificationInputsTests(unittest.TestCase):
    def _run(self):
        library = T0TemplateLibrary(
            "t0-input-test-v1", 8,
            (T0Template("state-stability", "invariant", "eq", "pre", "post", "sorted_public_scalar_storage_symbols"),),
        )
        pack = {
            "public_files": {"storage_symbols.json": {"symbols": [
                {"symbol_id": "storage.B.slot_0.flag", "path": "B.sol", "name": "flag", "domain": "source", "kind": "storage", "type": "bool"},
            ]}},
            "gold_access": "disabled",
        }
        return T0DeterministicProposer(library).propose(pack, attempt_id="t0-attempt").method_run

    def test_t0_method_run_uses_shared_candidate_input_contract(self) -> None:
        method_run = self._run()
        rows = candidates_from_method_run(
            method_run,
            campaign_id="t0-campaign",
            pair_key=PairKey("lineage", "instance", 1),
            arm="t0",
        )
        self.assertEqual(method_run.track, MethodTrack.T0)
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0].proposal_status, "candidate")
        self.assertEqual(rows[0].candidate["kind"], "invariant")
        self.assertEqual(rows[1].proposal_status, "abstain")
        self.assertEqual(rows[0].raw_response, {})

    def test_provider_response_count_mismatch_is_rejected(self) -> None:
        method_run = self._run()
        broken = type(method_run)(
            method_run.track, method_run.backbone, method_run.attempt_id,
            method_run.template_hash, method_run.artifact_pack_hash, method_run.settings,
            method_run.slots, ("one-response",), method_run.token_measurements, method_run.budget_checks,
        )
        with self.assertRaisesRegex(ValueError, "response count"):
            candidates_from_method_run(
                broken,
                campaign_id="campaign",
                pair_key=PairKey("lineage", "instance", 1),
                arm="t0",
            )


if __name__ == "__main__":
    unittest.main()
