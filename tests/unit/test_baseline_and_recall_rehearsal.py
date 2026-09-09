from __future__ import annotations

import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from scripts import run_baseline_and_recall_rehearsal


ROOT = Path(__file__).resolve().parents[2]


class BaselineAndRecallRehearsalTests(unittest.TestCase):
    def test_selection_report_is_outcome_blind_and_schema_valid(self) -> None:
        report_path = ROOT / "dataset/reports/m07_selection_rehearsal.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "schemas/baseline_selection_rehearsal.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(report)), [])
        self.assertEqual(run_baseline_and_recall_rehearsal.validate_selection_report(ROOT, report_path), [])
        self.assertEqual(report["baseline_subset"]["target_size"], 48)
        self.assertEqual(report["sensitivity_subset"]["target_size"], 24)
        self.assertTrue(report["outcome_blind"])

    def test_recall_report_keeps_two_denominators_separate(self) -> None:
        report_path = ROOT / "dataset/reports/m07_recall_rehearsal.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "schemas/recall_rehearsal.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(report)), [])
        self.assertEqual(run_baseline_and_recall_rehearsal.validate_recall_report(report_path), [])
        self.assertEqual(report["proposal_prefix"]["endpoint_separation"], "stored_ordered_proposals_only")
        self.assertEqual(report["end_to_end"]["endpoint_separation"], "scheduled_campaign_outcomes_only")


if __name__ == "__main__":
    unittest.main()
