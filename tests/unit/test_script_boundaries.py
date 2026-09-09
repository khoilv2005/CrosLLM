from __future__ import annotations

from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import validate_mutation_triggers


ROOT = Path(__file__).parents[2]


class ScriptBoundaryTests(unittest.TestCase):
    def test_all_generated_harness_runners_use_pinned_read_only_docker_argv(self) -> None:
        runners = sorted((ROOT / "dataset" / "harness").glob("*/normal_workflow_test.py"))
        self.assertEqual(len(runners), 16)
        for runner in runners:
            text = runner.read_text(encoding="utf-8")
            self.assertNotIn("wsl", text.lower(), runner)
            self.assertNotIn("shell=True", text, runner)
            self.assertIn("@sha256:", text, runner)
            self.assertIn("target=/work,readonly", text, runner)

    def test_active_mutation_and_artifact_tools_do_not_use_shell_strings(self) -> None:
        for name in ("validate_mutation_triggers.py", "export_across_artifacts.py"):
            text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertNotIn("shell=True", text, name)
            self.assertNotIn("wsl", text.lower(), name)
            self.assertIn("@sha256:", text, name)
        self.assertIn("--network=none", (ROOT / "scripts" / "validate_mutation_triggers.py").read_text(encoding="utf-8"))

    def test_mutation_runner_removes_named_container_after_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = root / "dataset" / "harness" / "mutation_tests"
            (harness / "contracts").mkdir(parents=True)
            (harness / "test").mkdir(parents=True)
            (root / "dataset" / "benchmark").mkdir(parents=True)
            (harness / "contracts" / "MutationTargets.sol").write_text("// fixture", encoding="utf-8")
            (root / "dataset" / "benchmark" / "mutation_operators.json").write_text(
                '{"operators":[{"operator_id":"OP_TEST","property_family":"replay",'
                '"transformation":"fixture","intended_security_property":"fixture",'
                '"negative_control_policy":"fixture"},'
                '{"operator_id":"OP_TEST_2","property_family":"input_validation",'
                '"transformation":"fixture","intended_security_property":"fixture",'
                '"negative_control_policy":"fixture"},'
                '{"operator_id":"OP_TEST_3","property_family":"logic",'
                '"transformation":"fixture","intended_security_property":"fixture",'
                '"negative_control_policy":"fixture"},'
                '{"operator_id":"OP_TEST_4","property_family":"message_handling",'
                '"transformation":"fixture","intended_security_property":"fixture",'
                '"negative_control_policy":"fixture"},'
                '{"operator_id":"OP_TEST_5","property_family":"quorum",'
                '"transformation":"fixture","intended_security_property":"fixture",'
                '"negative_control_policy":"fixture"},'
                '{"operator_id":"OP_TEST_6","property_family":"finality",'
                '"transformation":"fixture","intended_security_property":"fixture",'
                '"negative_control_policy":"fixture"}]}', encoding="utf-8"
            )
            validation_rows = []
            test_fragments = []
            for index in range(1, 7):
                operator_id = "OP_TEST" if index == 1 else f"OP_TEST_{index}"
                mutant = f"TargetMutant{index}"
                control = f"TargetControl{index}"
                test_case = f"test_{operator_id}()"
                validation_rows.append({
                    "operator_id": operator_id,
                    "mutant_contract": mutant,
                    "control_contract": control,
                    "test_case": test_case,
                    "trigger": "fixture",
                    "control_expectation": "fixture",
                })
                test_fragments.extend((mutant, control, test_case))
            (root / "dataset" / "benchmark" / "mutation_validation_spec.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "scope": "generated_development_mutation_harness_only",
                    "rows": validation_rows,
                }),
                encoding="utf-8",
            )
            (harness / "test" / "MutationTriggerVerificationTest.t.sol").write_text(
                "// " + " ".join(test_fragments), encoding="utf-8"
            )
            timeout = subprocess.TimeoutExpired(["docker", "run"], 1)
            cleanup = SimpleNamespace(returncode=0, stdout="", stderr="")
            with patch(
                "scripts.validate_mutation_triggers.subprocess.run",
                side_effect=[timeout, cleanup],
            ) as run, patch(
                "scripts.validate_mutation_triggers.extract_all_artifacts.create_compiler_cache_volume",
                return_value="crossllm-solc-test",
            ), patch(
                "scripts.validate_mutation_triggers.extract_all_artifacts.populate_compiler_cache_volume",
                return_value={"version": "0.8.36", "binary_sha256": "a" * 64},
            ), patch(
                "scripts.validate_mutation_triggers.extract_all_artifacts.remove_compiler_cache_volume",
            ):
                result = validate_mutation_triggers.main(
                    ["--root", str(root), "--timeout-seconds", "1"]
                )
        self.assertEqual(result, 1)
        command = run.call_args_list[0].args[0]
        self.assertIn("--name", command)
        self.assertIn("--network=none", command)
        name = command[command.index("--name") + 1]
        self.assertRegex(name, r"^crossllm-mutation-\d+$")
        cleanup_command = run.call_args_list[1].args[0]
        self.assertEqual(cleanup_command, ["docker", "rm", "-f", name])


if __name__ == "__main__":
    unittest.main()
