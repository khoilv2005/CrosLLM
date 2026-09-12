import unittest

from crossllm.methods.t0 import (
    T0DeterministicProposer,
    T0InputError,
    T0Template,
    T0TemplateLibrary,
)
from crossllm.methods.proposal import ProposalSlotStatus


class T0ProposerTests(unittest.TestCase):
    def _proposer(self) -> T0DeterministicProposer:
        library = T0TemplateLibrary(
            "t0-test-v1",
            8,
            (T0Template("state-stability", "invariant", "eq", "pre", "post", "sorted_public_scalar_storage_symbols"),),
        )
        return T0DeterministicProposer(library)

    def _pack(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "record_type": "public_evaluation_artifact_pack",
            "public_files": {
                "storage_symbols.json": {"schema_version": 1, "symbols": [
                    {"symbol_id": "storage.B.slot_2.z", "path": "B.sol", "name": "z", "domain": "destination", "kind": "storage", "type": "uint256"},
                    {"symbol_id": "storage.B.slot_1.a", "path": "B.sol", "name": "a", "domain": "source", "kind": "storage", "type": "bool"},
                ]},
            },
            "gold_access": "disabled",
        }

    def test_output_is_deterministic_and_compiled(self) -> None:
        proposer = self._proposer()
        first = proposer.propose(self._pack(), attempt_id="attempt")
        second = proposer.propose(self._pack(), attempt_id="attempt")
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual(len(first.method_run.slots), 8)
        self.assertEqual(first.method_run.slots[0].status, ProposalSlotStatus.CANDIDATE)
        self.assertEqual(first.method_run.slots[0].candidate["invariant_id"], "t0.state-stability.storage.B.slot_1.a")
        self.assertEqual(len(first.method_run.slots[0].canonical_ast_hash), 64)
        self.assertEqual(first.method_run.provider_responses, ())

    def test_empty_public_symbol_set_abstains_without_provider(self) -> None:
        proposer = self._proposer()
        pack = self._pack()
        pack["public_files"] = {"storage_symbols.json": {"schema_version": 1, "symbols": []}}
        run = proposer.propose(pack, attempt_id="attempt")
        self.assertTrue(all(slot.status is ProposalSlotStatus.ABSTAIN for slot in run.method_run.slots))
        self.assertEqual(run.candidate_hashes, ())

    def test_private_property_fields_are_rejected(self) -> None:
        proposer = self._proposer()
        pack = self._pack()
        pack["public_files"]["property_oracle"] = "must not enter T0"
        with self.assertRaises(T0InputError):
            proposer.propose(pack, attempt_id="attempt")


if __name__ == "__main__":
    unittest.main()
