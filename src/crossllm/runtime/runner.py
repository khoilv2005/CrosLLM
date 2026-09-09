"""Bounded worker execution for the development/evaluation runtime boundary.

The runner deliberately owns orchestration only.  A task callback is supplied by
the method/provider layer and may return a structured ``WorkerExecution``.  The
runner owns admission, lifecycle events, interruption policy, measured resource
records and deterministic result ordering.  Production deployments must still
run this boundary inside the immutable Docker/cgroup command produced by
``DockerWorkerCommandBuilder``.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from collections.abc import Mapping
from dataclasses import dataclass
from time import monotonic, perf_counter, thread_time
from typing import Any, Callable

from ..contracts import CampaignStatus
from .events import (
    AppendOnlyEventStore,
    AttemptState,
    CampaignStateMachine,
    InterruptionKind,
    ResumeAction,
)
from .resources import (
    AdmissionDecision,
    AdmissionStatus,
    ResourceRequest,
    ResourceSnapshot,
    ResourceUsage,
    WorkerResourceScheduler,
)
from .readiness import EvaluationLaunchGuard, ReadinessReport
from .telemetry import EffortPhase, TelemetryLedger, TelemetryRecord


_TERMINAL_STATUSES = {
    CampaignStatus.COMPLETED,
    CampaignStatus.TIMEOUT,
    CampaignStatus.UNSUPPORTED,
    CampaignStatus.PROVIDER_FAILURE,
    CampaignStatus.TOOL_FAILURE,
    CampaignStatus.NO_VALID_PROPOSAL,
}


@dataclass(frozen=True, slots=True)
class WorkerExecution:
    """Structured callback result with optional measured usage and event data."""

    status: CampaignStatus = CampaignStatus.COMPLETED
    result: object | None = None
    usage: ResourceUsage | None = None
    payload: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if self.status not in _TERMINAL_STATUSES:
            raise ValueError("worker execution must use a terminal campaign status")
        if self.payload is not None and not isinstance(self.payload, dict):
            raise ValueError("worker execution payload must be an object")


class WorkerFailure(RuntimeError):
    """Explicit task failure, including whether the attempt may be resumed."""

    def __init__(
        self,
        reason: str,
        *,
        status: CampaignStatus = CampaignStatus.TOOL_FAILURE,
        uncertain: bool = False,
        interruption: InterruptionKind = InterruptionKind.WORKER_RESTART,
    ) -> None:
        if not reason:
            raise ValueError("worker failure requires a reason")
        if status not in _TERMINAL_STATUSES:
            raise ValueError("worker failure status must be terminal")
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.uncertain = uncertain
        self.interruption = interruption


@dataclass(frozen=True, slots=True)
class WorkerTask:
    """One campaign attempt; retrying it never creates a new campaign ID."""

    campaign_id: str
    attempt_id: str
    request: ResourceRequest
    execute: Callable[[], object]
    max_resumes: int = 1

    def __post_init__(self) -> None:
        if not self.campaign_id or not self.attempt_id:
            raise ValueError("worker task requires campaign and attempt IDs")
        if self.request.campaign_id != self.campaign_id:
            raise ValueError("resource request campaign_id does not match task")
        if not callable(self.execute):
            raise ValueError("worker task execute must be callable")
        if self.max_resumes < 0:
            raise ValueError("max_resumes must be non-negative")


@dataclass(frozen=True, slots=True)
class WorkerRun:
    campaign_id: str
    attempt_id: str
    status: CampaignStatus
    state: str
    terminal: bool
    result: object | None
    error: str | None
    usage: ResourceUsage
    admission_reason: str | None
    resume_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "campaign_id": self.campaign_id,
            "attempt_id": self.attempt_id,
            "status": self.status.value,
            "state": self.state,
            "terminal": self.terminal,
            "result": self.result,
            "error": self.error,
            "usage": self.usage.as_resource_vector(),
            "admission_reason": self.admission_reason,
            "resume_count": self.resume_count,
        }


@dataclass(frozen=True, slots=True)
class WorkerBatchReport:
    """Ordered batch output plus immutable event/telemetry snapshots."""

    runs: tuple[WorkerRun, ...]
    events: tuple[object, ...]
    telemetry: tuple[TelemetryRecord, ...]
    resource_snapshot: ResourceSnapshot

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "runs": [run.as_dict() for run in self.runs],
            "event_count": len(self.events),
            "events": [event.as_dict() for event in self.events],
            "telemetry": [record.as_dict() for record in self.telemetry],
            "resource_snapshot": {
                "active_campaigns": self.resource_snapshot.active_campaigns,
                "queued_campaigns": self.resource_snapshot.queued_campaigns,
                "active_cpu_cores": self.resource_snapshot.active_cpu_cores,
                "active_memory_bytes": self.resource_snapshot.active_memory_bytes,
                "used_core_seconds": self.resource_snapshot.used_core_seconds,
                "used_input_tokens": self.resource_snapshot.used_input_tokens,
                "used_generated_tokens": self.resource_snapshot.used_generated_tokens,
                "active_solver_profiles": list(self.resource_snapshot.active_solver_profiles),
                "throttled_count": self.resource_snapshot.throttled_count,
            },
        }


@dataclass(frozen=True, slots=True)
class _Invocation:
    execution: WorkerExecution | None
    failure: WorkerFailure | None
    error: str | None
    usage: ResourceUsage


class WorkerRunner:
    """Run admitted tasks concurrently while retaining attempt identity.

    The implementation uses threads to keep the test/development boundary
    portable.  CPU/RAM enforcement is represented by the scheduler and must be
    enforced at deployment by the Docker/cgroup command; a Python callback is
    never treated as proof of an OS-level limit.
    """

    def __init__(
        self,
        scheduler: WorkerResourceScheduler | None = None,
        *,
        event_store: AppendOnlyEventStore | None = None,
        worker_id: str = "worker-development-1",
        clock: Callable[[], float] | None = None,
        timestamp: Callable[[], str] | None = None,
    ) -> None:
        if not worker_id:
            raise ValueError("worker_id is required")
        self.scheduler = scheduler or WorkerResourceScheduler()
        self.event_store = event_store or AppendOnlyEventStore()
        self.worker_id = worker_id
        self._clock = clock or monotonic
        self._timestamp = timestamp

    def run(
        self,
        tasks: list[WorkerTask] | tuple[WorkerTask, ...],
        *,
        resume_uncertain: bool = True,
    ) -> WorkerBatchReport:
        ordered_tasks = tuple(tasks)
        if not ordered_tasks:
            raise ValueError("at least one worker task is required")
        self._validate_tasks(ordered_tasks)
        pending = {task.campaign_id: task for task in ordered_tasks}
        machines: dict[str, CampaignStateMachine] = {}
        submitted_at: dict[str, float] = {}
        queued: dict[str, bool] = {}
        resume_interruptions: dict[str, InterruptionKind] = {}
        resume_counts: dict[str, int] = {task.campaign_id: 0 for task in ordered_tasks}
        outcomes: dict[str, WorkerRun] = {}
        telemetry = TelemetryLedger()
        active: dict[Future[_Invocation], tuple[str, WorkerTask, float, bool]] = {}

        max_workers = min(
            len(ordered_tasks),
            self.scheduler.envelope.max_concurrent_campaigns,
        )
        with ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="crossllm-worker") as executor:
            def reject(task: WorkerTask, decision: AdmissionDecision) -> None:
                machine = machines.setdefault(task.campaign_id, self._machine(task))
                if machine.state == AttemptState.PLANNED:
                    machine.start({"admission": "rejected", "reason": decision.reason})
                elif machine.state == AttemptState.RUNNING:
                    machine.mark_uncertain("admission_rejected_while_running", InterruptionKind.WORKER_RESTART)
                machine.finish(
                    CampaignStatus.UNSUPPORTED,
                    {"admission_rejected": True, "reason": decision.reason},
                )
                outcomes[task.campaign_id] = WorkerRun(
                    task.campaign_id,
                    task.attempt_id,
                    CampaignStatus.UNSUPPORTED,
                    AttemptState.TERMINAL,
                    True,
                    None,
                    f"admission_rejected:{decision.reason}",
                    ResourceUsage(),
                    decision.reason,
                    resume_counts[task.campaign_id],
                )

            def launch(task: WorkerTask, decision: AdmissionDecision) -> None:
                if decision.lease_id is None:
                    raise RuntimeError("admitted task has no lease")
                machine = machines.setdefault(task.campaign_id, self._machine(task))
                try:
                    if machine.state == AttemptState.PLANNED:
                        machine.start({
                            "lease_id": decision.lease_id,
                            "request": task.request.__dict__ if hasattr(task.request, "__dict__") else task.request.as_dict() if hasattr(task.request, "as_dict") else {
                                "cpu_cores": task.request.cpu_cores,
                                "memory_bytes": task.request.memory_bytes,
                                "solver_profile": task.request.solver_profile,
                            },
                        })
                    elif machine.state == AttemptState.UNCERTAIN:
                        machine.resume(resume_interruptions.get(task.campaign_id))
                    elif machine.state == AttemptState.TERMINAL:
                        raise ValueError("task attempt is already terminal; rerun is forbidden")
                    else:
                        raise ValueError("task attempt is no longer launchable")
                except Exception:
                    # A lease must not leak if lifecycle restoration itself fails.
                    self.scheduler.release(decision.lease_id, ResourceUsage())
                    raise
                queued_seconds = max(0.0, self._clock() - submitted_at[task.campaign_id])
                active[executor.submit(self._invoke, task)] = (
                    decision.lease_id,
                    task,
                    queued_seconds,
                    queued.get(task.campaign_id, False),
                )

            def handle_admission(task: WorkerTask, decision: AdmissionDecision) -> None:
                pending.pop(task.campaign_id, None)
                if decision.status is AdmissionStatus.ADMITTED:
                    launch(task, decision)
                elif decision.status is AdmissionStatus.REJECTED:
                    reject(task, decision)
                else:
                    raise RuntimeError("queued admission must remain pending")

            def release_and_process(lease_id: str, usage: ResourceUsage) -> None:
                for decision in self.scheduler.release(lease_id, usage):
                    task = pending.get(decision.campaign_id)
                    if task is None:
                        raise RuntimeError("scheduler admitted an unknown campaign")
                    handle_admission(task, decision)

            for task in ordered_tasks:
                machine = machines.setdefault(task.campaign_id, self._machine(task))
                if machine.state == AttemptState.TERMINAL:
                    # A completed campaign is an immutable observation, not a
                    # new replicate.  The callback is deliberately not called.
                    terminal_event = next(
                        event for event in reversed(self.event_store.events)
                        if event.campaign_id == task.campaign_id
                        and event.attempt_id == task.attempt_id
                        and event.event_type == "campaign_terminal"
                    )
                    outcomes[task.campaign_id] = WorkerRun(
                        task.campaign_id,
                        task.attempt_id,
                        machine.campaign_status,
                        AttemptState.TERMINAL,
                        True,
                        None,
                        "existing_terminal_attempt_not_rerun",
                        ResourceUsage(),
                        str(terminal_event.payload.get("reason")) if terminal_event.payload.get("reason") else None,
                        0,
                    )
                    pending.pop(task.campaign_id, None)
                    continue
                submitted_at[task.campaign_id] = self._clock()
                decision = self.scheduler.submit(task.request)
                if decision.status is AdmissionStatus.QUEUED:
                    queued[task.campaign_id] = True
                    continue
                handle_admission(task, decision)

            while active:
                done, _ = wait(tuple(active), return_when=FIRST_COMPLETED)
                for future in done:
                    lease_id, task, queued_seconds, was_queued = active.pop(future)
                    invocation = future.result()
                    telemetry.append(TelemetryRecord(
                        EffortPhase.METHOD_HORIZON,
                        invocation.usage,
                        campaign_id=task.campaign_id,
                        attempt_id=task.attempt_id,
                        worker_id=self.worker_id,
                        queue_seconds=queued_seconds,
                        throttled_seconds=queued_seconds if was_queued else 0.0,
                        throttle_count=1 if was_queued else 0,
                    ))
                    machine = machines[task.campaign_id]
                    if invocation.failure is not None and invocation.failure.uncertain:
                        failure = invocation.failure
                        machine.mark_uncertain(failure.reason, failure.interruption)
                        can_resume = (
                            resume_uncertain
                            and resume_counts[task.campaign_id] < task.max_resumes
                            and machine.policy.action_for(failure.interruption) is ResumeAction.RESUME_SAME_ATTEMPT
                        )
                        release_and_process(lease_id, invocation.usage)
                        if can_resume:
                            resume_counts[task.campaign_id] += 1
                            resume_interruptions[task.campaign_id] = failure.interruption
                            submitted_at[task.campaign_id] = self._clock()
                            pending[task.campaign_id] = task
                            decision = self.scheduler.submit(task.request)
                            if decision.status is AdmissionStatus.QUEUED:
                                queued[task.campaign_id] = True
                                continue
                            handle_admission(task, decision)
                        else:
                            outcomes[task.campaign_id] = WorkerRun(
                                task.campaign_id,
                                task.attempt_id,
                                failure.status,
                                AttemptState.UNCERTAIN,
                                False,
                                None,
                                failure.reason,
                                invocation.usage,
                                None,
                                resume_counts[task.campaign_id],
                            )
                        continue

                    if invocation.execution is not None:
                        execution = invocation.execution
                        payload = dict(execution.payload or {})
                        if invocation.error is not None:
                            payload["runner_error"] = invocation.error
                        machine.finish(execution.status, payload)
                        outcomes[task.campaign_id] = WorkerRun(
                            task.campaign_id,
                            task.attempt_id,
                            execution.status,
                            AttemptState.TERMINAL,
                            True,
                            execution.result,
                            invocation.error,
                            invocation.usage,
                            None,
                            resume_counts[task.campaign_id],
                        )
                    else:
                        error = invocation.error or "worker invocation failed"
                        failure_status = (
                            invocation.failure.status
                            if invocation.failure is not None
                            else CampaignStatus.TOOL_FAILURE
                        )
                        machine.finish(failure_status, {"error": error})
                        outcomes[task.campaign_id] = WorkerRun(
                            task.campaign_id,
                            task.attempt_id,
                            failure_status,
                            AttemptState.TERMINAL,
                            True,
                            None,
                            error,
                            invocation.usage,
                            None,
                            resume_counts[task.campaign_id],
                        )
                    release_and_process(lease_id, invocation.usage)

            # A queue can remain when cumulative quota is exhausted after all
            # active leases have ended.  Emit explicit unsupported terminal
            # records instead of silently dropping campaigns.
            for campaign_id, task in tuple(pending.items()):
                removed = self.scheduler.cancel_queued(campaign_id)
                reason = (
                    "queue_not_drained_after_active_work; quota or capacity unavailable"
                    if removed
                    else "pending_campaign_not_in_scheduler_queue"
                )
                reject(task, AdmissionDecision(AdmissionStatus.REJECTED, campaign_id, reason))
                pending.pop(campaign_id, None)

        return WorkerBatchReport(
            tuple(outcomes[task.campaign_id] for task in ordered_tasks),
            self.event_store.events,
            telemetry.records,
            self.scheduler.snapshot(),
        )

    def _machine(self, task: WorkerTask) -> CampaignStateMachine:
        kwargs: dict[str, object] = {}
        if self._timestamp is not None:
            kwargs["timestamp"] = self._timestamp
        campaign_events = [
            event for event in self.event_store.events
            if event.campaign_id == task.campaign_id
        ]
        terminal_attempts = {
            event.attempt_id for event in campaign_events if event.terminal
        }
        if terminal_attempts and task.attempt_id not in terminal_attempts:
            raise ValueError(
                "campaign already has a terminal attempt; a new attempt_id would rerun it"
            )
        existing = [
            event for event in campaign_events
            if event.campaign_id == task.campaign_id and event.attempt_id == task.attempt_id
        ]
        if existing:
            return CampaignStateMachine.restore(
                task.campaign_id,
                task.attempt_id,
                self.event_store,
                clock=self._clock,
                **kwargs,
            )
        return CampaignStateMachine(
            task.campaign_id,
            task.attempt_id,
            self.event_store,
            clock=self._clock,
            **kwargs,
        )

    @staticmethod
    def _validate_tasks(tasks: tuple[WorkerTask, ...]) -> None:
        campaigns = [task.campaign_id for task in tasks]
        attempts = [task.attempt_id for task in tasks]
        if len(campaigns) != len(set(campaigns)):
            raise ValueError("worker campaign IDs must be unique")
        if len(attempts) != len(set(attempts)):
            raise ValueError("worker attempt IDs must be unique")

    @staticmethod
    def _invoke(task: WorkerTask) -> _Invocation:
        started_wall = perf_counter()
        started_cpu = thread_time()
        try:
            value = task.execute()
            execution = value if isinstance(value, WorkerExecution) else WorkerExecution(result=value)
            error = None
            failure = None
        except WorkerFailure as caught:
            execution = None
            failure = caught
            error = caught.reason
        except TimeoutError as caught:
            execution = None
            failure = WorkerFailure(str(caught) or "worker timeout", status=CampaignStatus.TIMEOUT)
            error = failure.reason
        except Exception as caught:  # a crash is terminal unless explicitly marked uncertain
            execution = None
            failure = None
            error = f"{type(caught).__name__}: {caught}"
        elapsed = max(0.0, perf_counter() - started_wall)
        cpu_seconds = max(0.0, thread_time() - started_cpu) * task.request.cpu_cores
        provided_usage = execution.usage if execution is not None else None
        usage = provided_usage or ResourceUsage(
            cpu_core_seconds=cpu_seconds,
            wall_seconds=elapsed,
        )
        return _Invocation(execution, failure, error, usage)


class EvaluationRunner:
    """Evaluation executor that cannot start before the launch guard passes.

    The worker runner remains reusable for development rehearsals. This thin
    evaluation-only wrapper makes the safety boundary executable: readiness is
    checked before delegating the first task to ``WorkerRunner``. It does not
    manufacture readiness and it performs no provider work during the check.
    """

    def __init__(
        self,
        runner: WorkerRunner | None = None,
        *,
        guard: EvaluationLaunchGuard | None = None,
    ) -> None:
        self.runner = runner or WorkerRunner(worker_id="evaluation-worker-1")
        self.guard = guard or EvaluationLaunchGuard()

    def run(
        self,
        tasks: list[WorkerTask] | tuple[WorkerTask, ...],
        *,
        readiness_report: ReadinessReport,
        campaign_plan: Mapping[str, object] | None = None,
        resume_uncertain: bool = True,
    ) -> WorkerBatchReport:
        self.guard.assert_ready(
            readiness_report,
            campaign_plan=campaign_plan,
            campaign_ids=tuple(task.campaign_id for task in tasks),
        )
        return self.runner.run(tasks, resume_uncertain=resume_uncertain)


__all__ = [
    "WorkerBatchReport",
    "WorkerExecution",
    "EvaluationRunner",
    "WorkerFailure",
    "WorkerRun",
    "WorkerRunner",
    "WorkerTask",
]
