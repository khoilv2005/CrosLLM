from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from crossllm.contracts import ReplayStatus, SearchStatus
from crossllm.replay import WitnessAssessmentStatus
from crossllm.runtime import DevelopmentDryRun


class RuntimeDryRunTests(unittest.TestCase):
    def test_offline_rehearsal_covers_pipeline_and_writes_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            report = DevelopmentDryRun().run(path)
            self.assertTrue(report.proposal_compiled)
            self.assertEqual(report.smt_status, SearchStatus.SAT)
            self.assertEqual(report.search_status, SearchStatus.SAT)
            self.assertEqual(report.symbolic_search_status, SearchStatus.SAT)
            self.assertEqual(report.native_replay_status, ReplayStatus.PASS)
            self.assertEqual(report.independent_replay_status, "unknown")
            self.assertEqual(report.replay_assessment_status, WitnessAssessmentStatus.PENDING)
            self.assertIn("independent_replay_unknown", report.replay_assessment_reasons)
            self.assertTrue(report.resumed_same_attempt)
            self.assertEqual(report.method_event_count, 54)
            self.assertEqual(report.event_count, 58)
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 58)
            event_types = [
                json.loads(line)["event_type"]
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(event_types.count("method_started"), 3)
            self.assertEqual(event_types.count("provider_response"), 24)
            self.assertEqual(event_types.count("proposal_slot_recorded"), 24)
            self.assertEqual(event_types.count("method_completed"), 3)
            self.assertEqual(event_types[-1], "campaign_terminal")
            self.assertEqual(report.analysis["recall"]["X"]["value"], 1.0)
            for track in ("X", "P", "T0"):
                self.assertEqual(report.method_tracks[track]["slot_count"], 8)
                self.assertEqual(report.method_tracks[track]["candidate_count"], 8)
                self.assertEqual(report.method_tracks[track]["provider_call_count"], 8)
            self.assertEqual(len(report.method_tracks["shared_request_hash"]), 64)
            self.assertIsNone(report.telemetry["input_tokens"])

    def test_fault_rehearsal_preserves_failures_and_resumes_crash_same_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            report = DevelopmentDryRun().run(base / "events.jsonl", base / "fault-events.jsonl")
            self.assertIsNotNone(report.fault_rehearsal)
            scenarios = {row["campaign_id"]: row for row in report.fault_rehearsal["scenarios"]}
            self.assertEqual(scenarios["worker_crash"]["status"], "completed")
            self.assertEqual(scenarios["worker_crash"]["resume_count"], 1)
            self.assertEqual(scenarios["timeout"]["status"], "timeout")
            self.assertEqual(scenarios["provider_failure"]["status"], "provider_failure")
            self.assertEqual(scenarios["corrupted_blob"]["status"], "tool_failure")
            self.assertEqual(scenarios["disk_full"]["status"], "tool_failure")
            self.assertEqual(len((base / "fault-events.jsonl").read_text(encoding="utf-8").splitlines()), 12)


if __name__ == "__main__":
    unittest.main()
