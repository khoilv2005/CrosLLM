from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from crossllm.baselines import (
    BaselineResult,
    ConditionedAdapter,
    ConditionedSpec,
    EffortVector,
    ExternalToolAdapter,
    FidelityStatus,
    GPTScanAudit,
    GPTScanSpec,
    ToolSpec,
    compare_parity,
)
from crossllm.contracts import SearchStatus


class GPTScanConditionedTests(unittest.TestCase):
    def _tool(self, *, network_policy: str = "offline") -> ToolSpec:
        return ToolSpec(
            "fixture", "python", ("-c", "import json; print(json.dumps([]))"),
            "upstream-commit", "a" * 64, "solidity-evm", network_policy=network_policy,
        )

    def test_gptscan_adaptation_is_labeled_and_transport_is_bound(self) -> None:
        audit = GPTScanAudit(
            "gptscan-upstream-1", ("learned-scoring", "retrieval"),
            ("learned-scoring",), ("retrieval",), FidelityStatus.TRANSPARENT_ADAPTATION,
            parity_fixture_hash="a" * 64,
        )
        spec = GPTScanSpec("G-Q", "Qwen", "ollama", self._tool(network_policy="provider_only"), audit)
        self.assertEqual(spec.as_dict()["audit"]["claim_label"], "transparent_adaptation")
        self.assertEqual(len(spec.identity_hash), 64)
        with self.assertRaisesRegex(ValueError, "provider_only"):
            GPTScanSpec("G-Q", "Qwen", "ollama", self._tool(), audit)

    def test_parity_report_exposes_differences_without_relabeling_results(self) -> None:
        tool = self._tool()
        clean = ExternalToolAdapter().run(tool, Path.cwd())
        different = BaselineResult(tool, SearchStatus.SAT, 0, "a" * 64, "b" * 64, (), 0.1, "findings_returned")
        report = compare_parity(clean, different, fixture_hash="c" * 64)
        self.assertFalse(report.equal)
        self.assertIn("status", report.differences[0])

    def test_conditioned_spec_keeps_property_harness_and_track_storage_effort(self) -> None:
        spec = ConditionedSpec(
            "H0", "conditioned", self._tool(), "a" * 64, "b" * 64, "c" * 64, "d" * 64, "common-harness-v1",
        )
        result = ConditionedAdapter().run(
            spec, Path.cwd(),
            effort=EffortVector(1.0, cpu_seconds=0.5, track_steps=4, storage_steps=3, solver_queries=2),
        )
        self.assertTrue(result.as_dict()["track_storage_separated"])
        self.assertEqual(result.as_dict()["effort"]["storage_steps"], 3)
        with self.assertRaisesRegex(ValueError, "explain missing effort"):
            ConditionedAdapter().run(spec, Path.cwd())


if __name__ == "__main__":
    unittest.main()
