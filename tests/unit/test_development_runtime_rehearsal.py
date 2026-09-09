from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from scripts import run_development_runtime_rehearsal


ROOT = Path(__file__).resolve().parents[2]


class DevelopmentRuntimeRehearsalTests(unittest.TestCase):
    def test_rehearsal_hashes_raw_events_and_covers_e2e_faults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            report = run_development_runtime_rehearsal.build_report(
                ROOT,
                events_path=base / "events.jsonl",
                fault_path=base / "fault.jsonl",
            )
            schema = json.loads((ROOT / "schemas/development_runtime_rehearsal.schema.json").read_text(encoding="utf-8"))
            self.assertEqual(list(Draft202012Validator(schema).iter_errors(report)), [])
            self.assertEqual(report["summary"]["event_count"], 58)
            self.assertEqual(report["summary"]["method_event_count"], 54)
            self.assertEqual(report["summary"]["fault_event_count"], 12)
            self.assertEqual(report["ollama_cloud_calls"], 0)
            self.assertFalse(report["admission_eligible"])
            path = base / "report.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            self.assertEqual(run_development_runtime_rehearsal.validate_report(ROOT, path), [])

    def test_raw_event_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            report = run_development_runtime_rehearsal.build_report(
                ROOT,
                events_path=base / "events.jsonl",
                fault_path=base / "fault.jsonl",
            )
            with (base / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write("tampered\n")
            path = base / "report.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            errors = run_development_runtime_rehearsal.validate_report(ROOT, path)
        self.assertIn("events hash mismatch", errors)


if __name__ == "__main__":
    unittest.main()
