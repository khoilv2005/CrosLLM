from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from crossllm.cli import main


class CLIDryRunTests(unittest.TestCase):
    def test_dry_run_exports_events_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            export_path = Path(directory) / "new-output-directory" / "events.jsonl"
            report_path = Path(directory) / "new-output-directory" / "report.json"
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                exit_code = main([
                    "dry-run", "--export", str(export_path), "--report", str(report_path)
                ])
            output = json.loads(stream.getvalue())
            saved_report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(output["smt_status"], "sat")
            self.assertEqual(output["search_status"], "sat")
            self.assertTrue(output["resumed_same_attempt"])
            self.assertEqual(saved_report, output)
            self.assertEqual(len(export_path.read_text(encoding="utf-8").splitlines()), 58)
            self.assertEqual(output["method_event_count"], 54)


if __name__ == "__main__":
    unittest.main()
