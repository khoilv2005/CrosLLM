from __future__ import annotations

import unittest
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts import run_isolation_canary

from crossllm.runtime import (
    CanaryStatus,
    IsolationStatus,
    MountSpec,
    VersionBlock,
    VersionIdentity,
    WorkerIsolationPolicy,
)


class RuntimeIsolationCanaryTests(unittest.TestCase):
    ROOT = Path(__file__).parents[2]

    def test_checked_docker_canary_report_matches_schema(self) -> None:
        report = json.loads((self.ROOT / "dataset" / "reports" / "isolation_canary.json").read_text(encoding="utf-8"))
        schema = json.loads((self.ROOT / "schemas" / "isolation_canary.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(report)), [])
        self.assertEqual(run_isolation_canary.validate_report(self.ROOT), [])
        self.assertEqual(report["passed_count"], 6)
        self.assertFalse(report["admission_eligible"])
    def test_private_gold_broadcast_and_non_allowlisted_network_are_blocked(self) -> None:
        policy = WorkerIsolationPolicy(allowed_network_hosts=("ollama.internal",))
        decisions = policy.validate(
            [MountSpec("/controlled/public", "/work/artifact", "public_artifact")],
            endpoint="http://ollama.internal:11434/api",
            broadcast=False,
        )
        self.assertTrue(all(decision.status == IsolationStatus.ALLOWED for decision in decisions))
        self.assertEqual(
            policy.check_mounts([MountSpec("/private/gold", "/work/gold", "private_gold")]).status,
            IsolationStatus.BLOCKED,
        )
        self.assertEqual(policy.check_broadcast(broadcast=True).status, IsolationStatus.BLOCKED)
        self.assertEqual(policy.check_network("https://untrusted.example/api").status, IsolationStatus.BLOCKED)

    def test_non_http_endpoint_is_not_treated_as_provider_access(self) -> None:
        policy = WorkerIsolationPolicy(allowed_network_hosts=("ollama.internal",))
        self.assertEqual(policy.check_network("file:///private/gold").status, IsolationStatus.BLOCKED)
        with self.assertRaisesRegex(PermissionError, "private gold"):
            policy.assert_compliant([MountSpec("/private/gold", "/gold", "private_gold")])

    def test_writable_and_model_weight_mounts_are_blocked_even_if_mislabeled(self) -> None:
        policy = WorkerIsolationPolicy()
        with self.assertRaisesRegex(PermissionError, "writable bind"):
            policy.assert_compliant([MountSpec("/public", "/work", "public_artifact", read_only=False)])
        with self.assertRaisesRegex(PermissionError, "model-weight"):
            policy.assert_compliant([MountSpec("/cache", "/root/.ollama/models", "public_artifact")])

    def test_version_drift_blocks_without_explicit_deviation(self) -> None:
        base = VersionIdentity("model:a", "sha256:a", "p" * 64, "q" * 64, "tool:a")
        changed = VersionIdentity("model:a", "sha256:b", "p" * 64, "q" * 64, "tool:a")
        block = VersionBlock("block-1", base)
        passed = block.observe(base, canary_passed=True, evidence_hash="e" * 64)
        blocked = block.observe(changed, canary_passed=True, evidence_hash="f" * 64)
        self.assertEqual(passed.status, CanaryStatus.PASSED)
        self.assertEqual(blocked.status, CanaryStatus.BLOCKED)
        self.assertIn("drift", blocked.reason)

    def test_failed_canary_and_explicit_deviation_are_distinct(self) -> None:
        identity = VersionIdentity("model:a", None, "p" * 64, "q" * 64, "tool:a")
        block = VersionBlock("block-2", identity)
        failed = block.observe(identity, canary_passed=False, evidence_hash="e" * 64)
        deviation = block.register_deviation(identity, "approved provider endpoint migration", "d" * 64)
        self.assertEqual(failed.status, CanaryStatus.BLOCKED)
        self.assertEqual(deviation.status, CanaryStatus.DEVIATION)
        self.assertEqual(len(block.observations), 2)


if __name__ == "__main__":
    unittest.main()
