from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from crossllm.baselines import ExternalToolAdapter, ResourceEnvelope, ToolSpec, normalize_findings
from crossllm.contracts import SearchStatus


class BaselineTests(unittest.TestCase):
    def spec(self, executable: str = "python") -> ToolSpec:
        return ToolSpec("fixture-tool", executable, ("-c", "import json; print(json.dumps([]))"), "commit-1", "a" * 64, "source")

    def test_missing_binary_is_unsupported_not_no_finding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = ExternalToolAdapter().run(self.spec("definitely-not-installed-crossllm"), Path(directory))
        self.assertEqual(result.status, SearchStatus.UNSUPPORTED)
        self.assertFalse(result.clean)
        self.assertEqual(result.reason, "executable_missing")

    def test_native_clean_output_is_bounded_unsat_only_after_successful_parse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = ExternalToolAdapter().run(self.spec(), Path(directory))
        self.assertEqual(result.status, SearchStatus.BOUNDED_UNSAT)
        self.assertTrue(result.clean)
        self.assertIsNotNone(result.stdout_hash)

    def test_nonzero_and_malformed_output_are_not_clean(self) -> None:
        bad = ToolSpec("bad", "python", ("-c", "raise SystemExit(2)"), "commit-1", "a" * 64, "source")
        malformed = ToolSpec("malformed", "python", ("-c", "print('not json')"), "commit-1", "a" * 64, "source")
        with tempfile.TemporaryDirectory() as directory:
            adapter = ExternalToolAdapter()
            self.assertEqual(adapter.run(bad, Path(directory)).status, SearchStatus.CRASH)
            parsed = adapter.run(malformed, Path(directory))
        self.assertEqual(parsed.status, SearchStatus.CRASH)
        self.assertIn("output_parse_failure", parsed.reason or "")

    def test_normalization_preserves_raw_and_rejects_incomplete_rows(self) -> None:
        findings = normalize_findings("slither", [{"check": "reentrancy", "description": "call"}])
        self.assertEqual(findings[0].category, "reentrancy")
        self.assertEqual(findings[0].raw["description"], "call")
        with self.assertRaisesRegex(ValueError, "category/message"):
            normalize_findings("slither", [{"check": "only-check"}])

    def test_tool_identity_and_declared_envelope_are_exported(self) -> None:
        spec = ToolSpec(
            "fixture-tool", "python", ("-c", "print('[]')"), "commit-1", "a" * 64,
            "source", resource_envelope=ResourceEnvelope(cpu_cores=2, memory_mib=2048, pids=32, wall_seconds=10),
            network_policy="offline", timeout_seconds=10,
        )
        exported = spec.as_dict()
        self.assertEqual(exported["network_policy"], "offline")
        self.assertEqual(exported["resource_envelope"]["memory_mib"], 2048)
        self.assertEqual(len(exported["argv_hash"]), 64)
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            ToolSpec(
                "bad", "python", (), "commit-1", "a" * 64, "source", timeout_seconds=11,
                resource_envelope=ResourceEnvelope(wall_seconds=10),
            )

    def test_resource_limits_are_declarations_in_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = ExternalToolAdapter().run(self.spec(), Path(directory))
        self.assertEqual(result.as_dict()["resource_enforcement"], "declared_only")

    def test_slither_and_ityfuzz_native_shapes_are_normalized_without_losing_raw(self) -> None:
        slither = normalize_findings(
            "slither-s0",
            {"success": True, "results": {"detectors": [{"check": "reentrancy", "description": "call", "elements": [{"source_mapping": "A.sol:1"}]}]}},
            output_schema="slither_json",
        )
        ityfuzz = normalize_findings(
            "ityfuzz-i0",
            {"issues": [{"type": "assertion", "message": "bad state", "id": "issue-1"}]},
            output_schema="ityfuzz_json",
        )
        self.assertEqual(slither[0].category, "reentrancy")
        self.assertEqual(slither[0].location, "A.sol:1")
        self.assertEqual(slither[0].raw["elements"][0]["source_mapping"], "A.sol:1")
        self.assertEqual(ityfuzz[0].finding_id, "issue-1")
        with self.assertRaisesRegex(ValueError, "detector list"):
            normalize_findings("slither", {"results": {}}, output_schema="slither_json")


if __name__ == "__main__":
    unittest.main()
