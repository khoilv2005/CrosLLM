from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from scripts import run_development_calibration_rehearsal


ROOT = Path(__file__).resolve().parents[2]


class CalibrationRehearsalTests(unittest.TestCase):
    def test_rehearsal_is_hash_bound_and_never_claims_provider_execution(self) -> None:
        report = run_development_calibration_rehearsal.build_report(ROOT)
        schema = json.loads((ROOT / "schemas/calibration_rehearsal.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(report)), [])
        self.assertEqual(report["executed_provider_calls"], 0)
        self.assertTrue(report["synthetic_fixture_inputs"])
        self.assertFalse(report["admission_eligible"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rehearsal.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            self.assertEqual(run_development_calibration_rehearsal.validate_report(ROOT, path), [])

    def test_tampered_report_is_rejected(self) -> None:
        report = run_development_calibration_rehearsal.build_report(ROOT)
        report["executed_provider_calls"] = 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rehearsal.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            errors = run_development_calibration_rehearsal.validate_report(ROOT, path)
        self.assertIn("calibration rehearsal report hash mismatch", errors)
        self.assertIn("executed_provider_calls mismatch", errors)
if __name__ == "__main__":
    unittest.main()
