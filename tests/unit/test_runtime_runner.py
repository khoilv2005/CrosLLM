from __future__ import annotations

from threading import Barrier, Lock
import time
import unittest

from crossllm.contracts import CampaignStatus
from crossllm.runtime import (
    AppendOnlyEventStore,
    AdmissionStatus,
    InterruptionKind,
    Quota,
    ResourceEnvelope,
    ResourceRequest,
    ResourceUsage,
    WorkerExecution,
    WorkerFailure,
    WorkerResourceScheduler,
    WorkerRunner,
    WorkerTask,
)


class RuntimeRunnerTests(unittest.TestCase):
    def _task(self, campaign_id: str, execute, *, profile: str | None = None, cpu: int = 1) -> WorkerTask:
        return WorkerTask(
            campaign_id,
            f"{campaign_id}-attempt",
            ResourceRequest(campaign_id, cpu, 4, solver_profile=profile),
            execute,
        )

    def test_runs_admitted_campaigns_concurrently_and_exports_terminal_events(self) -> None:
        barrier = Barrier(2)
        tasks = [
            self._task("c1", lambda: (barrier.wait(timeout=2), "one")[1]),
            self._task("c2", lambda: (barrier.wait(timeout=2), "two")[1]),
        ]
        report = WorkerRunner(
            WorkerResourceScheduler(ResourceEnvelope(cpu_cores=2, memory_bytes=16, max_concurrent_campaigns=2)),
            worker_id="test-worker",
        ).run(tasks)
        self.assertEqual([run.status for run in report.runs], [CampaignStatus.COMPLETED] * 2)
        self.assertTrue(all(run.terminal for run in report.runs))
        self.assertEqual(len(report.events), 4)
        self.assertEqual(len(report.telemetry), 2)
        self.assertEqual(report.resource_snapshot.active_campaigns, 0)

    def test_solver_profile_is_serialized_by_scheduler(self) -> None:
        lock = Lock()
        active = 0
        peak = 0

        def execute() -> str:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return "ok"

        scheduler = WorkerResourceScheduler(ResourceEnvelope(cpu_cores=2, memory_bytes=16, max_concurrent_campaigns=2))
        report = WorkerRunner(scheduler).run([
            self._task("c1", execute, profile="z3"),
            self._task("c2", execute, profile="z3"),
        ])
        self.assertEqual(peak, 1)
        self.assertEqual(scheduler.snapshot().throttled_count, 1)
        self.assertEqual(report.telemetry[1].throttle_count, 1)

    def test_uncertain_worker_failure_resumes_same_attempt_without_new_campaign(self) -> None:
        calls = 0

        def execute() -> WorkerExecution:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise WorkerFailure(
                    "crash while provider response was in flight",
                    uncertain=True,
                )
            return WorkerExecution(result="recovered")

        task = self._task("c1", execute)
        report = WorkerRunner().run([task])
        run = report.runs[0]
        self.assertEqual(calls, 2)
        self.assertEqual(run.status, CampaignStatus.COMPLETED)
        self.assertEqual(run.resume_count, 1)
        self.assertTrue(run.terminal)
        self.assertEqual(run.attempt_id, task.attempt_id)
        self.assertEqual(
            [event.event_type for event in report.events],
            ["campaign_started", "attempt_uncertain", "campaign_started", "campaign_terminal"],
        )
        self.assertEqual(report.events[2].payload["resumed"], True)

    def test_timeout_and_admission_rejection_remain_explicit(self) -> None:
        timeout_task = self._task(
            "timeout",
            lambda: (_ for _ in ()).throw(TimeoutError("deadline")),
        )
        rejected = WorkerTask(
            "too-large",
            "too-large-attempt",
            ResourceRequest("too-large", 2, 4),
            lambda: "never",
        )
        runner = WorkerRunner(
            WorkerResourceScheduler(ResourceEnvelope(cpu_cores=1, memory_bytes=8, max_concurrent_campaigns=1))
        )
        report = runner.run([timeout_task, rejected])
        self.assertEqual(report.runs[0].status, CampaignStatus.TIMEOUT)
        self.assertEqual(report.runs[1].status, CampaignStatus.UNSUPPORTED)
        self.assertIn("admission_rejected", report.runs[1].error or "")
        self.assertEqual(report.resource_snapshot.queued_campaigns, 0)

    def test_queue_exhaustion_cancels_ghost_requests(self) -> None:
        scheduler = WorkerResourceScheduler(
            ResourceEnvelope(cpu_cores=1, memory_bytes=8, max_concurrent_campaigns=1),
            Quota(max_core_seconds=0.5),
        )

        def consume_quota() -> WorkerExecution:
            return WorkerExecution(usage=ResourceUsage(cpu_core_seconds=1.0))

        report = WorkerRunner(scheduler).run([
            WorkerTask(
                "active", "active-attempt",
                ResourceRequest("active", 1, 1, estimated_core_seconds=0.1),
                consume_quota,
            ),
            WorkerTask(
                "queued", "queued-attempt",
                ResourceRequest("queued", 1, 1, estimated_core_seconds=0.1),
                lambda: "must not run",
            ),
        ])
        self.assertEqual(report.runs[1].status, CampaignStatus.UNSUPPORTED)
        self.assertIn("queue_not_drained", report.runs[1].error or "")
        self.assertEqual(report.resource_snapshot.queued_campaigns, 0)

    def test_existing_terminal_attempt_is_not_rerun(self) -> None:
        store = AppendOnlyEventStore()
        first_calls = 0

        def first() -> str:
            nonlocal first_calls
            first_calls += 1
            return "completed"

        task = self._task("terminal-once", first)
        first_report = WorkerRunner(event_store=store).run([task])
        self.assertEqual(first_report.runs[0].status, CampaignStatus.COMPLETED)

        second_calls = 0

        def must_not_run() -> str:
            nonlocal second_calls
            second_calls += 1
            raise AssertionError("terminal campaign was rerun")

        second_report = WorkerRunner(event_store=store).run([
            self._task("terminal-once", must_not_run),
        ])
        self.assertEqual(first_calls, 1)
        self.assertEqual(second_calls, 0)
        self.assertEqual(second_report.runs[0].status, CampaignStatus.COMPLETED)
        self.assertIn("not_rerun", second_report.runs[0].error or "")
        self.assertEqual(len(store.events), 2)

    def test_terminal_campaign_cannot_be_restarted_with_a_new_attempt_id(self) -> None:
        store = AppendOnlyEventStore()
        first = self._task("attempt-id-drift", lambda: "done")
        WorkerRunner(event_store=store).run([first])
        changed_attempt = WorkerTask(
            "attempt-id-drift",
            "attempt-id-drift-new",
            first.request,
            lambda: "must not run",
        )
        with self.assertRaisesRegex(ValueError, "new attempt_id"):
            WorkerRunner(event_store=store).run([changed_attempt])

    def test_runner_restart_resumes_persisted_uncertain_attempt(self) -> None:
        store = AppendOnlyEventStore()
        calls = 0

        def flaky() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise WorkerFailure(
                    "response was lost in flight",
                    uncertain=True,
                    interruption=InterruptionKind.LOST_RESPONSE,
                )
            return "recovered"

        task = self._task("restartable", flaky)
        interrupted = WorkerRunner(event_store=store).run([task], resume_uncertain=False)
        self.assertEqual(interrupted.runs[0].state, "uncertain")
        resumed = WorkerRunner(event_store=store).run([task])
        self.assertEqual(resumed.runs[0].status, CampaignStatus.COMPLETED)
        self.assertEqual(resumed.runs[0].attempt_id, task.attempt_id)
        self.assertEqual(calls, 2)
        self.assertEqual(
            [event.event_type for event in store.events],
            ["campaign_started", "attempt_uncertain", "campaign_started", "campaign_terminal"],
        )


if __name__ == "__main__":
    unittest.main()
