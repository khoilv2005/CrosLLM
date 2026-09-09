from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from scripts import run_differential_spike


ROOT = Path(__file__).resolve().parents[2]


class DifferentialSpikeTests(unittest.TestCase):
    def test_report_matches_schema_and_is_explicitly_structural_only(self) -> None:
        schema = json.loads((ROOT / "schemas/symbolic_to_source_differential.schema.json").read_text(encoding="utf-8"))
        report = json.loads((ROOT / "dataset/reports/symbolic_to_source_differential.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(report)), [])
        self.assertEqual(run_differential_spike.validate_report(ROOT), [])
        self.assertEqual(report["differential_status"], "structural_only")
        self.assertFalse(report["direct_trace_comparable"])
        self.assertFalse(report["admission_eligible"])

    def test_tampered_source_identity_is_rejected(self) -> None:
        report = json.loads((ROOT / "dataset/reports/symbolic_to_source_differential.json").read_text(encoding="utf-8"))
        report["source_replay_report_hash"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "differential.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            errors = run_differential_spike.validate_report(ROOT, path)
        self.assertIn("differential spike report hash mismatch", errors)
        self.assertIn("source replay report hash mismatch", errors)


if __name__ == "__main__":
    unittest.main()
