from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from scripts import run_source_backed_replays


ROOT = Path(__file__).parents[2]


class SourceBackedReplayCollectionTests(unittest.TestCase):
    def test_collection_matches_schema_and_covers_all_development_hosts(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "source_backed_replays.schema.json").read_text(
                encoding="utf-8"
            )
        )
        report = json.loads(
            (ROOT / "dataset" / "reports" / "source_backed_replays.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(report)), [])
        self.assertEqual(run_source_backed_replays.validate_report(ROOT), [])
        self.assertEqual(
            [row["lineage_id"] for row in report["receipts"]],
            list(run_source_backed_replays.LINEAGES),
        )
        self.assertFalse(report["admission_eligible"])
        self.assertTrue(all(row["result"]["status"] == "pass" for row in report["receipts"]))

    def test_receipt_tampering_is_detected_without_rewriting_the_report(self) -> None:
        report = json.loads(
            (ROOT / "dataset" / "reports" / "source_backed_replays.json").read_text(
                encoding="utf-8"
            )
        )
        report["receipts"][1]["source_file_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replays.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            errors = run_source_backed_replays.validate_report(ROOT, path)
        self.assertIn("source-backed replays report hash mismatch", errors)
        self.assertIn("chainbridge: source_file_sha256 mismatch", errors)


if __name__ == "__main__":
    unittest.main()
