import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.validate_source_case_compilation import (
    _docker_command,
    _report,
    compile_workspace,
    CompilationResult,
)


class SourceCaseCompilationTests(unittest.TestCase):
    def test_docker_command_is_read_only_and_build_only(self) -> None:
        command = _docker_command(Path("C:/workspace"), "forge.example@sha256:" + "a" * 64)
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop=ALL", command)
        self.assertIn("build", command)
        self.assertNotIn("test", command)
        self.assertIn("type=bind,source=C:\\workspace,target=/work,readonly", command)

    def test_compile_workspace_preserves_nonzero_as_compile_failure(self) -> None:
        class Completed:
            returncode = 1
            stdout = b"stdout"
            stderr = b"stderr"

        with tempfile.TemporaryDirectory() as directory:
            with patch("scripts.validate_source_case_compilation.subprocess.run", return_value=Completed()):
                result = compile_workspace(Path(directory), image="forge@sha256:" + "b" * 64, timeout_seconds=1)
        self.assertEqual(result[0], "compile_fail")
        self.assertEqual(result[1], 1)
        self.assertEqual(result[2], b"stdout")

    def test_report_never_calls_compile_pass_verified(self) -> None:
        report = _report(
            [CompilationResult("lineage", "case", "compile_pass", 0, "a" * 64, "b" * 64)],
            manifest=Path("benchmark.public.jsonl"),
            image="forge@sha256:" + "c" * 64,
            timeout_seconds=300,
        )
        self.assertEqual(report["status"], "pass")
        self.assertFalse(report["candidate_search_run"])
        self.assertFalse(report["witness_check_run"])
        self.assertFalse(report["independent_replay_run"])
        self.assertEqual(report["counts"], {"compile_pass": 1})
        self.assertEqual(len(report["report_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
