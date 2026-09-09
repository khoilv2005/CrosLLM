from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.validate_reconciliation import build_report, validate_report


ROOT = Path(__file__).resolve().parents[2]


class ReconciliationTests(unittest.TestCase):
    def test_repository_map_is_complete_and_hash_bound(self) -> None:
        report = build_report(ROOT, generated_on="2026-09-09")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reconciliation.json"
            path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.assertEqual(validate_report(ROOT, path), [])
        self.assertEqual(len(report["entries"]), 6)

    def test_tampered_file_hash_is_rejected(self) -> None:
        report = build_report(ROOT, generated_on="2026-09-09")
        report["entries"][0]["file_sha256"]["protocol/models.json"] = "0" * 64  # type: ignore[index]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reconciliation.json"
            path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            errors = validate_report(ROOT, path)
        self.assertTrue(any("file hash mismatch" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
