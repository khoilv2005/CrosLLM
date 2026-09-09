from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from crossllm.contracts import CampaignStatus, EventLog
from crossllm.runtime import (
    AppendOnlyEventStore,
    CampaignStateMachine,
    InterruptionKind,
    PersistentEventStore,
    ResumeAction,
    ResumePolicy,
)


class RuntimeEventTests(unittest.TestCase):
    def test_uncertain_resume_uses_same_attempt_and_terminal_is_idempotently_exportable(self) -> None:
        store = AppendOnlyEventStore()
        clock_values = iter([1.0, 2.0, 3.0, 4.0])
        machine = CampaignStateMachine(
            "campaign-1", "attempt-1", store, clock=lambda: next(clock_values), timestamp=lambda: "2026-09-08T00:00:00Z"
        )
        machine.start()
        machine.mark_uncertain("worker_crash_in_flight")
        machine.resume()
        machine.finish(CampaignStatus.COMPLETED, {"result": "development_only"})
        self.assertEqual(machine.snapshot().state, "terminal")
        self.assertEqual(machine.snapshot().attempt_id, "attempt-1")
        self.assertEqual(len(store.events), 4)
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "one.jsonl"
            second = Path(directory) / "two.jsonl"
            store.export_jsonl(first)
            store.export_jsonl(second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
        with self.assertRaisesRegex(ValueError, "terminal"):
            machine.resume()

    def test_completed_campaign_cannot_finish_again(self) -> None:
        store = AppendOnlyEventStore()
        machine = CampaignStateMachine("campaign-1", "attempt-1", store, clock=lambda: 1.0, timestamp=lambda: "t")
        machine.start()
        machine.finish(CampaignStatus.TIMEOUT)
        with self.assertRaisesRegex(ValueError, "terminal"):
            machine.finish(CampaignStatus.COMPLETED)

    def test_store_rejects_duplicate_terminal_attempt(self) -> None:
        store = AppendOnlyEventStore()
        machine = CampaignStateMachine("campaign-1", "attempt-1", store, clock=lambda: 1.0, timestamp=lambda: "t")
        machine.start()
        machine.finish(CampaignStatus.COMPLETED)
        duplicate = store.events[-1]
        with self.assertRaisesRegex(ValueError, "duplicate event_id"):
            store.append(duplicate)

    def test_store_rejects_events_after_terminal_attempt(self) -> None:
        store = AppendOnlyEventStore()
        machine = CampaignStateMachine("campaign-after-terminal", "attempt-after-terminal", store, clock=lambda: 1.0, timestamp=lambda: "t")
        machine.start()
        machine.finish(CampaignStatus.COMPLETED)
        with self.assertRaisesRegex(ValueError, "after terminal"):
            store.append(EventLog(
                event_id="post-terminal-event",
                event_type="provider_response",
                campaign_id="campaign-after-terminal",
                attempt_id="attempt-after-terminal",
                timestamp="t",
                payload={},
            ))

    def test_persisted_uncertain_attempt_restores_and_resumes_same_attempt(self) -> None:
        store = AppendOnlyEventStore()
        clock_values = iter([1.0, 2.0, 3.0])
        machine = CampaignStateMachine(
            "campaign-2", "attempt-2", store, clock=lambda: next(clock_values), timestamp=lambda: "t"
        )
        machine.start()
        machine.mark_uncertain("provider_connection_lost", InterruptionKind.LOST_RESPONSE)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            store.export_jsonl(path)
            restored_store = AppendOnlyEventStore.load_jsonl(path)
            restored = CampaignStateMachine.restore(
                "campaign-2", "attempt-2", restored_store,
                clock=lambda: next(clock_values), timestamp=lambda: "t",
            )
            self.assertEqual(restored.snapshot().state, "uncertain")
            restored.resume(InterruptionKind.LOST_RESPONSE)
            self.assertEqual(restored.snapshot().attempt_id, "attempt-2")
            self.assertEqual(len(restored_store.events), 3)

    def test_completed_campaign_is_not_resumable_after_restart(self) -> None:
        store = AppendOnlyEventStore()
        machine = CampaignStateMachine("campaign-3", "attempt-3", store, clock=lambda: 1.0, timestamp=lambda: "t")
        machine.start()
        machine.finish(CampaignStatus.COMPLETED)
        restored = CampaignStateMachine.restore("campaign-3", "attempt-3", store, clock=lambda: 2.0, timestamp=lambda: "t")
        with self.assertRaisesRegex(ValueError, "terminal"):
            restored.resume()

    def test_version_drift_is_blocked_by_fixed_resume_policy(self) -> None:
        policy = ResumePolicy(version_drift=ResumeAction.BLOCK)
        self.assertEqual(policy.action_for(InterruptionKind.VERSION_DRIFT), ResumeAction.BLOCK)
        store = AppendOnlyEventStore()
        machine = CampaignStateMachine("campaign-4", "attempt-4", store, policy=policy, clock=lambda: 1.0, timestamp=lambda: "t")
        machine.start()
        machine.mark_uncertain("runtime_version_changed", InterruptionKind.VERSION_DRIFT)
        with self.assertRaisesRegex(ValueError, "blocked by policy"):
            machine.resume(InterruptionKind.VERSION_DRIFT)

    def test_restore_preserves_interruption_kind_when_resume_argument_is_omitted(self) -> None:
        store = AppendOnlyEventStore()
        machine = CampaignStateMachine("campaign-5", "attempt-5", store, clock=lambda: 1.0, timestamp=lambda: "t")
        machine.start()
        machine.mark_uncertain("version drift", InterruptionKind.VERSION_DRIFT)
        restored = CampaignStateMachine.restore(
            "campaign-5", "attempt-5", store, clock=lambda: 2.0, timestamp=lambda: "t"
        )
        with self.assertRaisesRegex(ValueError, "blocked by policy"):
            restored.resume()

    def test_corrupted_jsonl_is_rejected_without_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corrupted.jsonl"
            path.write_text('{"event_id": "missing-rest-of-record"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid event JSONL"):
                AppendOnlyEventStore.load_jsonl(path)

    def test_persistent_store_commits_each_event_and_restores_same_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime" / "events.jsonl"
            path.parent.mkdir()
            store = PersistentEventStore(path)
            machine = CampaignStateMachine(
                "campaign-persisted",
                "attempt-persisted",
                store,
                clock=iter([1.0, 2.0, 3.0]).__next__,
                timestamp=lambda: "t",
            )
            machine.start({"plan_hash": "plan-dev"})
            machine.mark_uncertain("worker_restarted", InterruptionKind.WORKER_RESTART)
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)

            restarted = PersistentEventStore(path)
            restored = CampaignStateMachine.restore(
                "campaign-persisted",
                "attempt-persisted",
                restarted,
                clock=lambda: 3.0,
                timestamp=lambda: "t",
            )
            restored.resume()
            restored.finish(CampaignStatus.COMPLETED, {"result": "recovered"})
            recovered = PersistentEventStore(path)
            self.assertEqual(len(recovered.events), 4)
            self.assertEqual(
                [event.event_type for event in recovered.events],
                ["campaign_started", "attempt_uncertain", "campaign_started", "campaign_terminal"],
            )

    def test_persistent_store_rejects_non_file_and_corrupt_stream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            with self.assertRaisesRegex(ValueError, "regular file"):
                PersistentEventStore(directory_path)
            path = directory_path / "events.jsonl"
            path.write_text('{"schema_version": 1}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid event JSONL"):
                PersistentEventStore(path)


if __name__ == "__main__":
    unittest.main()
