from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from scripts import run_backend_feasibility_spike


ROOT = Path(__file__).resolve().parents[2]


class BackendFeasibilitySpikeTests(unittest.TestCase):
    def test_report_matches_schema_and_covers_all_m002_capabilities(self) -> None:
        schema = json.loads((ROOT / "schemas/backend_feasibility_spike.schema.json").read_text(encoding="utf-8"))
        report = json.loads((ROOT / "dataset/reports/backend_feasibility_spike.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(report)), [])
        self.assertEqual(run_backend_feasibility_spike.validate_report(ROOT), [])
        self.assertEqual(
            set(report["capabilities"]),
            {"snapshot_restore", "transaction_stepping", "symbolic_storage", "channel_actions", "witness_extraction"},
        )
        self.assertFalse(report["admission_eligible"])

    def test_tampered_capability_is_rejected(self) -> None:
        report = json.loads((ROOT / "dataset/reports/backend_feasibility_spike.json").read_text(encoding="utf-8"))
        report["capabilities"]["symbolic_storage"]["status"] = "fail"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backend.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            errors = run_backend_feasibility_spike.validate_report(ROOT, path)
        self.assertIn("backend feasibility report hash mismatch", errors)
        self.assertIn("symbolic_storage capability is not pass", errors)


if __name__ == "__main__":
    unittest.main()
