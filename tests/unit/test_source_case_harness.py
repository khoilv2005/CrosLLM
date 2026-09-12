import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.run_source_case_harness import (
    HarnessResult,
    _docker_command,
    _report,
    run_harness,
)


class SourceCaseHarnessTests(unittest.TestCase):
    def test_docker_command_is_read_only_and_runs_test_path(self) -> None:
        command = _docker_command(
            Path("C:/workspace"),
            "forge.example@sha256:" + "a" * 64,
            test_path="test/ReplayEvidence.t.sol",
            match_test="test_normal_workflow",
        )
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop=ALL", command)
        self.assertIn("--network=none", command)
        self.assertIn("test", command)
        self.assertIn("--match-path", command)
        self.assertIn("test/ReplayEvidence.t.sol", command)
        self.assertIn("--match-test", command)
        self.assertIn("test_normal_workflow", command)
        self.assertEqual(command.count("--network=none"), 1)

    def test_nonzero_foundry_build_is_not_a_pass(self) -> None:
        class Completed:
            def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b""):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "scripts.run_source_case_harness.subprocess.run",
                side_effect=[Completed(1, b"stdout", b"stderr")],
            ) as run:
                result = run_harness(
                    Path(directory), image="forge@sha256:" + "b" * 64,
                    test_path="test/Replay.t.sol", match_test=None, timeout_seconds=1,
                )
        self.assertEqual(result[0], "fail")
        self.assertEqual(result[1], 1)
        self.assertEqual(run.call_count, 1)

    def test_timeout_removes_only_the_named_probe_container(self) -> None:
        class Completed:
            def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b""):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "scripts.run_source_case_harness.subprocess.run",
                side_effect=[
                    Completed(0),
                    subprocess.TimeoutExpired(["docker", "run"], 1),
                    Completed(0),
                ],
            ) as run:
                result = run_harness(
                    Path(directory), image="forge@sha256:" + "b" * 64,
                    test_path="test/Replay.t.sol", match_test="test_case", timeout_seconds=1,
                )
        self.assertEqual(result[0], "timeout")
        self.assertEqual(result[4], "foundry_test_timeout")
        self.assertEqual(
            run.call_args_list[-1].args[0],
            ["docker", "rm", "-f", f"crossllm-source-case-{os.getpid()}-test"],
        )

    def test_probe_report_is_not_candidate_verification(self) -> None:
        report = _report(
            HarnessResult("lineage", "case", "pass", 0, "a" * 64, "b" * 64),
            image="forge@sha256:" + "c" * 64,
            match_test=None,
            timeout_seconds=300,
        )
        self.assertEqual(report["status"], "pass")
        self.assertFalse(report["gold_fields_read"])
        self.assertFalse(report["candidate_specific"])
        self.assertFalse(report["xlir_search_run"])
        self.assertFalse(report["witness_check_run"])
        self.assertFalse(report["independent_replay_run"])
        self.assertEqual(len(report["report_sha256"]), 64)
        json.dumps(report)


if __name__ == "__main__":
    unittest.main()
