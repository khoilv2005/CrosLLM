from __future__ import annotations

import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from scripts import review_historical_candidates


ROOT = Path(__file__).parents[2]


class HistoricalCandidateReviewTests(unittest.TestCase):
    def test_current_report_is_deterministic_and_fail_closed(self) -> None:
        self.assertEqual(review_historical_candidates.validate_report(ROOT), [])
        rows = review_historical_candidates.read_jsonl(
            ROOT / "dataset" / "reports" / "historical_candidate_reviews.jsonl"
        )
        schema = json.loads(
            (ROOT / "schemas" / "historical_candidate_review.schema.json").read_text(
                encoding="utf-8"
            )
        )
        validator = Draft202012Validator(schema)
        self.assertEqual(len(rows), 6)
        for row in rows:
            self.assertEqual(list(validator.iter_errors(row)), [])
            self.assertFalse(row["admission_eligible"])
            self.assertIn(row["admission_status"], {"candidate", "rejected"})
            self.assertTrue(row["blocking_reasons"])

    def test_shared_lineage_is_not_counted_as_independent(self) -> None:
        cases = [
            {
                "case_id": "a",
                "protocol": "A",
                "lineage_id": "shared",
                "admission_status": "candidate",
                "source_ids": ["s"],
            },
            {
                "case_id": "b",
                "protocol": "B",
                "lineage_id": "shared",
                "admission_status": "candidate",
                "source_ids": ["s"],
            },
        ]
        rows = review_historical_candidates.review_cases(
            cases, {"sources": [{"source_id": "s"}]}
        )
        self.assertEqual(
            {row["lineage_independence"]["status"] for row in rows}, {"fail"}
        )
        self.assertTrue(all(not row["admission_eligible"] for row in rows))

    def test_unknown_source_and_missing_gates_fail_closed(self) -> None:
        cases = [
            {
                "case_id": "case_one",
                "protocol": "Demo",
                "lineage_id": "demo",
                "admission_status": "candidate",
                "source_ids": ["missing"],
            }
        ]
        rows = review_historical_candidates.review_cases(cases, {"sources": []})
        row = rows[0]
        self.assertEqual(row["gates"]["source_registry_binding"]["status"], "fail")
        self.assertEqual(row["gates"]["trigger_validation"]["status"], "pending")
        self.assertFalse(row["admission_eligible"])


if __name__ == "__main__":
    unittest.main()
