from __future__ import annotations

import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from scripts import validate_replay_negative_controls


ROOT = Path(__file__).parents[2]


class ReplayNegativeControlTests(unittest.TestCase):
    def test_six_case_report_matches_schema_and_is_non_admission(self) -> None:
        report = json.loads((ROOT / "dataset" / "reports" / "replay_negative_controls.json").read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "schemas" / "replay_negative_controls.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(report)), [])
        self.assertEqual(validate_replay_negative_controls.validate_report(ROOT), [])
        self.assertEqual(report["case_count"], 6)
        self.assertEqual(report["passed_count"], 6)
        self.assertTrue(report["all_passed"])
        self.assertFalse(report["admission_eligible"])

    def test_case_ids_are_exactly_the_required_m05_05_controls(self) -> None:
        report = json.loads((ROOT / "dataset" / "reports" / "replay_negative_controls.json").read_text(encoding="utf-8"))
        self.assertEqual(
            report["case_ids"],
            ["wrong_property", "altered_witness", "infeasible_signature", "wrong_initial_state", "callback_ordering", "patched_control"],
        )
        self.assertTrue(all(row["passed"] for row in report["cases"]))


if __name__ == "__main__":
    unittest.main()
