from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from scripts import run_analysis_rehearsal


ROOT = Path(__file__).resolve().parents[2]


class AnalysisRehearsalTests(unittest.TestCase):
    def test_synthetic_rehearsal_has_full_outputs_and_schema(self) -> None:
        report_path = ROOT / "dataset/reports/m09_analysis_rehearsal.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "schemas/analysis_rehearsal.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(report)), [])
        self.assertEqual(run_analysis_rehearsal.validate_report(ROOT, report_path), [])
        self.assertEqual(report["analysis"]["table_count"], 11)
        self.assertEqual(len(report["figures"]), 5)
        self.assertEqual(report["provider_calls"], 0)
        self.assertFalse(report["admission_eligible"])

    def test_tampered_report_is_rejected(self) -> None:
        report = run_analysis_rehearsal.build_report(ROOT)
        report["provider_calls"] = 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "analysis.json"
            path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            errors = run_analysis_rehearsal.validate_report(ROOT, path)
        self.assertIn("analysis rehearsal report hash mismatch", errors)
        self.assertIn("provider_calls mismatch", errors)


if __name__ == "__main__":
    unittest.main()
