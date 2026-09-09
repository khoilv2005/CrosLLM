from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from scripts import run_sensitivity_matrix_rehearsal


ROOT = Path(__file__).resolve().parents[2]


class SensitivityMatrixRehearsalTests(unittest.TestCase):
    def test_report_matches_schema_and_expands_the_prespecified_cartesian_product(self) -> None:
        schema = json.loads((ROOT / "schemas/sensitivity_matrix_rehearsal.schema.json").read_text(encoding="utf-8"))
        report = json.loads((ROOT / "dataset/reports/m07_sensitivity_matrix_rehearsal.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(report)), [])
        self.assertEqual(run_sensitivity_matrix_rehearsal.validate_report(ROOT), [])
        self.assertEqual(report["cell_count"], 13824)
        self.assertEqual(report["eligibility_counts"], {"pending": 13824, "eligible": 0, "unsupported": 0})
        self.assertFalse(report["admission_eligible"])

    def test_tampered_matrix_hash_is_rejected(self) -> None:
        report = json.loads((ROOT / "dataset/reports/m07_sensitivity_matrix_rehearsal.json").read_text(encoding="utf-8"))
        report["matrix_hash"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sensitivity.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            errors = run_sensitivity_matrix_rehearsal.validate_report(ROOT, path)
        self.assertIn("sensitivity matrix rehearsal report hash mismatch", errors)
        self.assertIn("sensitivity matrix rehearsal content mismatch", errors)


if __name__ == "__main__":
    unittest.main()
