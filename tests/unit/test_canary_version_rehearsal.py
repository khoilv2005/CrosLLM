from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from scripts import run_canary_version_rehearsal


ROOT = Path(__file__).resolve().parents[2]


class CanaryVersionRehearsalTests(unittest.TestCase):
    def test_rehearsal_covers_pass_failure_drift_and_deviation(self) -> None:
        report = run_canary_version_rehearsal.build_report(ROOT)
        schema = json.loads((ROOT / "schemas/canary_version_rehearsal.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(report)), [])
        self.assertTrue(report["all_passed"])
        self.assertEqual(report["provider_calls"], 0)
        self.assertFalse(report["admission_eligible"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canary.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            self.assertEqual(run_canary_version_rehearsal.validate_report(ROOT, path), [])

    def test_tampered_status_is_rejected(self) -> None:
        report = run_canary_version_rehearsal.build_report(ROOT)
        report["provider_calls"] = 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canary.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            errors = run_canary_version_rehearsal.validate_report(ROOT, path)
        self.assertIn("canary version rehearsal report hash mismatch", errors)
        self.assertIn("provider_calls mismatch", errors)


if __name__ == "__main__":
    unittest.main()
