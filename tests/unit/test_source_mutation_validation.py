from __future__ import annotations

import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from scripts import validate_source_mutations


ROOT = Path(__file__).parents[2]


class SourceMutationValidationTests(unittest.TestCase):
    def test_source_backed_receipt_matches_schema_and_stays_non_admission(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "source_mutation_evidence.schema.json").read_text(
                encoding="utf-8"
            )
        )
        validator = Draft202012Validator(schema)
        rows = [
            json.loads(line)
            for line in (ROOT / "dataset" / "reports" / "source_mutation_evidence.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        self.assertEqual(len(rows), 2)
        self.assertEqual(validate_source_mutations.validate_report(ROOT), [])
        for row in rows:
            self.assertEqual(list(validator.iter_errors(row)), [])
            self.assertTrue(row["source_backed"])
            self.assertTrue(row["control_pair_verified"])
            self.assertFalse(row["independent_property_validation"])
            self.assertFalse(row["independent_trigger_validation"])
            self.assertFalse(row["admission_eligible"])
            self.assertEqual(row["network_mode"], "none")
            self.assertEqual(row["control_status"], "PASS")
            self.assertEqual(row["mutant_status"], "PASS")

    def test_exact_patch_anchor_is_required_and_changes_source(self) -> None:
        spec = validate_source_mutations.load_spec()
        row = spec["rows"][0]
        source = (ROOT / "dataset" / "harness" / "celer_cbridge" / "contracts" / "CBridge.sol").read_text(
            encoding="utf-8"
        )
        mutant, patch_hash = validate_source_mutations._patch_source(
            source, row["patch_anchor"], row["patch_replacement"]
        )
        self.assertNotEqual(source, mutant)
        self.assertEqual(len(patch_hash), 64)
        with self.assertRaisesRegex(ValueError, "exactly once"):
            validate_source_mutations._patch_source(
                source + row["patch_anchor"], row["patch_anchor"], row["patch_replacement"]
            )

    def test_runner_uses_network_isolation_and_read_only_mounts(self) -> None:
        command = validate_source_mutations._docker_command(
            ROOT / "build" / "source-mutation-stage",
            "test_replay_nonce_control",
            "crossllm-solc-test",
        )
        self.assertIn("--network=none", command)
        self.assertIn("--read-only", command)
        self.assertIn("@sha256:", command[-1] if "@sha256:" in command[-1] else " ".join(command))
        command_text = " ".join(command)
        self.assertIn("target=/work,readonly", command_text)
        self.assertIn("target=/base,readonly", command_text)
        self.assertIn("target=/compiler,readonly", command_text)
        self.assertIn("--use", command)
        self.assertEqual(command[command.index("--use") + 1], "/compiler/solc")


if __name__ == "__main__":
    unittest.main()
