from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from scripts import run_source_backed_replay


ROOT = Path(__file__).parents[2]


class SourceBackedReplayTests(unittest.TestCase):
    def test_receipt_matches_schema_and_is_explicitly_non_admission(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "source_backed_replay.schema.json").read_text(
                encoding="utf-8"
            )
        )
        report = json.loads(
            (ROOT / "dataset" / "reports" / "source_backed_replay.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(report)), [])
        self.assertEqual(run_source_backed_replay.validate_report(ROOT), [])
        self.assertEqual(report["result"]["status"], "pass")
        self.assertEqual(report["result"]["test_count"], 3)
        self.assertEqual(report["result"]["passed_tests"], 3)
        self.assertEqual(report["result"]["failed_tests"], 0)
        self.assertTrue(report["native_evm_replay"])
        self.assertFalse(report["independent_evaluator"])
        self.assertFalse(report["independent_property_validation"])
        self.assertFalse(report["independent_trigger_validation"])
        self.assertFalse(report["admission_eligible"])
        self.assertEqual(report["network_mode"], "none")

    def test_report_hash_and_source_identity_are_tamper_checked(self) -> None:
        original = json.loads(
            (ROOT / "dataset" / "reports" / "source_backed_replay.json").read_text(
                encoding="utf-8"
            )
        )
        original["source_file_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.json"
            path.write_text(json.dumps(original), encoding="utf-8")
            errors = run_source_backed_replay.validate_report(ROOT, path)
        self.assertIn("report hash mismatch", errors)
        self.assertIn("source_file_sha256 mismatch", errors)

    def test_replay_spec_binds_artifact_initialization_and_profile_hashes(self) -> None:
        report = json.loads(
            (ROOT / "dataset" / "reports" / "source_backed_replay.json").read_text(
                encoding="utf-8"
            )
        )
        spec = report["replay_spec"]
        self.assertEqual(
            spec["artifact_hash"],
            report["artifact_manifest_sha256"],
        )
        self.assertEqual(spec["initialization_hash"], report["initialization_sha256"])
        self.assertEqual(spec["profile_hash"], report["profile_sha256"])
        self.assertEqual(
            spec["support_matrix_hash"],
            json.loads(
                (ROOT / "dataset" / "reports" / "evm_support_matrix_celer_cbridge.json").read_text(
                    encoding="utf-8"
                )
            )["matrix"]["matrix_hash"],
        )
        self.assertEqual(spec["compiler_version"], "0.8.9")
        self.assertEqual(spec["network_mode"], "none")
        self.assertIn("@sha256:", spec["image_ref"])
        self.assertIn("@sha256:", spec["compiler_image_ref"])


if __name__ == "__main__":
    unittest.main()
