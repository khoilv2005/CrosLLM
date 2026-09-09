from __future__ import annotations

import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[2]


class MutationEvidenceTests(unittest.TestCase):
    def test_development_receipt_matches_schema_and_stays_non_admission(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "mutation_trigger_evidence.schema.json").read_text(
                encoding="utf-8"
            )
        )
        validator = Draft202012Validator(schema)
        rows = [
            json.loads(line)
            for line in (ROOT / "dataset" / "benchmark" / "trigger_validation_evidence.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        self.assertEqual(len(rows), 10)
        for row in rows:
            self.assertEqual(list(validator.iter_errors(row)), [])
            self.assertFalse(row["admission_eligible"])
            self.assertFalse(row["independent_source_validation"])
            self.assertEqual(row["network_mode"], "none")
        self.assertEqual(
            {row["property_family"] for row in rows},
            {"replay", "input_validation", "logic", "message_handling", "quorum", "finality"},
        )


if __name__ == "__main__":
    unittest.main()
