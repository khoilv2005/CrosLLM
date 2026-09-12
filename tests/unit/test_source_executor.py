from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts import source_executor


class SourceExecutorTests(unittest.TestCase):
    def _request(self, root: Path, predicate: dict[str, object]) -> dict[str, object]:
        (root / "test").mkdir()
        digest = "a" * 64
        return {
            "lineage_id": "across",
            "case_id": "eval_across_ctrl_01",
            "instance_id": "eval_across_ctrl_01",
            "source_workspace": str(root),
            "source_case_identity": {
                "lineage_id": "across",
                "case_id": "eval_across_ctrl_01",
            },
            "runtime_hash": digest,
            "artifact_hash": "b" * 64,
            "deployment_hash": "c" * 64,
            "canonical_ast_hash": "d" * 64,
            "initial_state_hash": "e" * 64,
            "source_domain": "DomainA",
            "destination_domain": "DomainB",
            "runtime": {
                "runtime_mode": "source_backed_local_evm",
                "source_domain": "DomainA",
                "destination_domain": "DomainB",
                "metadata": {
                    "source_backed": True,
                    "test_contract": "AcrossSourceBackedHarnessTest",
                },
            },
            "predicate": predicate,
            "predicate_lowering": {"root": "true"},
            "symbol_bindings": [{
                "symbol_id": "storage.Ethereum_SpokePool.slot_2155.pausedDeposits",
                "symbol_type": "bool",
                "domain": "shared",
                "contract": "Ethereum_SpokePool",
                "slot": 2155,
                "offset_bytes": 29,
                "getter": "Ethereum_SpokePool.pausedDeposits()",
                "state_locations": ["pre", "post"],
                "status": "bound",
                "executable": True,
            }],
            "actions": [
                {"action_id": "action:001", "caller_role": "depositor", "domain": "DomainA", "contract": "Ethereum_SpokePool", "selector": "0x7b939232", "executable": True},
                {"action_id": "action:002", "caller_role": "owner_setup", "domain": "DomainA", "contract": "Ethereum_SpokePool", "selector": "0x8624c35c", "executable": True},
                {"action_id": "action:003", "caller_role": "relayer", "domain": "DomainB", "contract": "Ethereum_SpokePool", "selector": "0xdeff4b24", "executable": True},
            ],
            "observation_points": ["deposit_nonce"],
        }

    def test_candidate_source_is_predicate_specific_and_source_backed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self._request(root, {
                "kind": "binary",
                "operator": "eq",
                "left": {"kind": "symbol", "symbol_id": "storage.Ethereum_SpokePool.slot_2155.pausedDeposits", "state": "post"},
                "right": {"kind": "literal", "type": "bool", "value": False},
            })
            prepared = source_executor._prepare(request)
            source = source_executor._candidate_source(prepared)
            self.assertIn("test_normal_source_backed_deposit_and_fast_fill", source)
            self.assertIn("sourcePool.pausedDeposits()", source)
            self.assertIn("CANDIDATE_HOLDS", source)
            self.assertNotIn("mutation_patch", source)
            self.assertNotIn("property_assessment", source)

    def test_pre_state_is_captured_before_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self._request(root, {
                "kind": "binary",
                "operator": "eq",
                "left": {"kind": "symbol", "symbol_id": "storage.Ethereum_SpokePool.slot_2155.pausedDeposits", "state": "pre"},
                "right": {"kind": "literal", "type": "bool", "value": False},
            })
            source = source_executor._candidate_source(source_executor._prepare(request))
            self.assertRegex(source, r"bool pre_[0-9a-f]{16} = sourcePool\.pausedDeposits\(\);")

    def test_unsupported_quantifier_and_non_across_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self._request(root, {"kind": "quantifier", "operator": "forall"})
            with self.assertRaises(source_executor.AdapterUnsupported):
                source_executor._prepare(request)
            request["lineage_id"] = "arbitrum_token_bridge"
            with self.assertRaises(source_executor.AdapterUnsupported):
                source_executor._prepare(request)

    def test_witness_retains_bindings_for_independent_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self._request(root, {
                "kind": "symbol",
                "symbol_id": "storage.Ethereum_SpokePool.slot_2155.pausedDeposits",
                "state": "post",
            })
            prepared = source_executor._prepare(request)
            receipt = source_executor.ExecutionReceipt("pass", None, 0, "f" * 64, "0" * 64, prepared.test_path, "test_candidate_search")
            witness = source_executor._witness(prepared, receipt)
            self.assertEqual(witness["engine_id"], source_executor.ENGINE_ID)
            self.assertEqual(len(witness["trace_hash"]), 64)
            self.assertTrue(witness["symbol_bindings"])
            self.assertEqual([a["action_id"] for a in witness["actions"]], ["action:001", "action:003"])

    def test_foundry_json_parser_accepts_trailing_log_prefix(self) -> None:
        payload = {"test_results": {"test_candidate_search()": {"status": "Success"}}}
        parsed = source_executor._parse_foundry_json(("notice\n" + json.dumps(payload)).encode())
        self.assertEqual(parsed, payload)


if __name__ == "__main__":
    unittest.main()
