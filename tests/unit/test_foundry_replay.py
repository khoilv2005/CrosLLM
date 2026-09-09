from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from crossllm.contracts import ReplayStatus
from crossllm.replay import FoundryReplaySpec, classify_foundry_failure, summarize_foundry_json
from crossllm.replay.process import ProcessOutcome
from crossllm.replay.foundry import FoundryDockerReplay


class FoundryReplayTests(unittest.TestCase):
    def spec(self, project: Path, **kwargs: object) -> FoundryReplaySpec:
        params: dict[str, object] = {
            "image_ref": "ghcr.io/foundry-rs/foundry@sha256:" + "a" * 64,
            "project_path": project,
            "tool_revision": "forge-1",
            "artifact_hash": "b" * 64,
            "initialization_hash": "c" * 64,
            "profile_hash": "d" * 64,
            "semantic_engine": "foundry-evm",
        }
        params.update(kwargs)
        return FoundryReplaySpec(**params)

    def test_foundry_json_counts_success_and_failure(self) -> None:
        payload = {
            "test/Bridge.t.sol:BridgeTest": {
                "test_results": {
                    "test_ok()": {"status": "Success"},
                    "test_bad()": {"status": "Failure"},
                }
            }
        }
        self.assertEqual(summarize_foundry_json(payload), (2, 1, 1))

    def test_command_is_isolated_and_identity_hash_changes_with_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            first = self.spec(project)
            second = self.spec(project, support_matrix_hash="e" * 64)
            command = first.command(docker_executable="docker")
            self.assertIn("--network=none", command)
            self.assertIn("--read-only", command)
            self.assertIn("--cap-drop=ALL", command)
            self.assertIn("--entrypoint", command)
            self.assertIn("HOME=/tmp/crossllm-home", command)
            self.assertIn("SVM_HOME=/tmp/crossllm-svm-home", command)
            self.assertIn("readonly", " ".join(command))
            self.assertNotEqual(first.spec_hash, second.spec_hash)
            bridge_command = self.spec(project, network_mode="bridge").command()
            self.assertIn("/tmp:rw,nosuid,size=1g", bridge_command)
            self.assertNotIn("/tmp:rw,noexec,nosuid,size=1g", bridge_command)

    def test_invalid_scope_and_output_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            with self.assertRaisesRegex(ValueError, "immutable"):
                self.spec(project, image_ref="foundry:latest")
            with self.assertRaisesRegex(ValueError, "network_mode"):
                self.spec(project, network_mode="host")
        with self.assertRaisesRegex(ValueError, "no test_results"):
            summarize_foundry_json({})
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            with self.assertRaisesRegex(ValueError, "compiler_image_ref"):
                self.spec(project, compiler_version="0.8.36", compiler_volume="crossllm-solc")
            with self.assertRaisesRegex(ValueError, "compiler_volume"):
                self.spec(
                    project,
                    compiler_version="0.8.36",
                    compiler_volume="bad volume",
                    compiler_image_ref="ghcr.io/argotorg/solc@sha256:" + "a" * 64,
                )

    def test_locked_compiler_volume_is_mounted_and_used_by_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            spec = self.spec(
                project,
                compiler_version="0.8.36",
                compiler_volume="crossllm-solc-test",
                compiler_image_ref="ghcr.io/argotorg/solc@sha256:" + "a" * 64,
            )
            command = spec.command()
            joined = " ".join(command)
            self.assertIn("type=volume,src=crossllm-solc-test,dst=/compiler,readonly", joined)
            self.assertIn("--use /compiler/solc", joined)
            self.assertNotIn("--use 0.8.36", joined)

    def test_compiler_environment_failures_are_not_claimed_as_test_failures(self) -> None:
        status, reason = classify_foundry_failure("can't install missing solc 0.8.20 in offline mode")
        self.assertEqual((status, reason), (ReplayStatus.UNSUPPORTED, "compiler_missing"))
        status, reason = classify_foundry_failure("error sending request for url https://binaries.soliditylang.org")
        self.assertEqual((status, reason), (ReplayStatus.UNKNOWN, "compiler_install_unavailable"))
        status, reason = classify_foundry_failure('"/tmp/.svm/0.8.20/solc-0.8.20": Permission denied')
        self.assertEqual((status, reason), (ReplayStatus.UNKNOWN, "compiler_execution_denied"))

    def test_successful_foundry_output_returns_success_without_name_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            stdout = (
                b'{"test/Bridge.t.sol:BridgeTest":{"test_results":'
                b'{"test_ok()":{"status":"Success"}}}}'
            )
            with patch("crossllm.replay.foundry.shutil.which", return_value="/usr/bin/docker"), \
                 patch("crossllm.replay.foundry.run_process", return_value=ProcessOutcome(0, stdout, b"")):
                result = FoundryDockerReplay().run(self.spec(project))
            self.assertEqual(result.status, ReplayStatus.PASS)
            self.assertEqual(result.exit_code, 0)
            self.assertEqual((result.test_count, result.passed_tests, result.failed_tests), (1, 1, 0))


if __name__ == "__main__":
    unittest.main()
