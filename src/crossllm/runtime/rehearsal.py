"""Fault-injection rehearsal for the development runtime (M08.08)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..contracts import CampaignStatus
from .events import InterruptionKind
from .resources import ResourceRequest
from .runner import WorkerBatchReport, WorkerFailure, WorkerRunner, WorkerTask


@dataclass(frozen=True, slots=True)
class FaultRehearsalReport:
    export_path: str
    batch: WorkerBatchReport

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "export_path": self.export_path,
            "scenarios": [
                {
                    "campaign_id": run.campaign_id,
                    "status": run.status.value,
                    "terminal": run.terminal,
                    "error": run.error,
                    "resume_count": run.resume_count,
                }
                for run in self.batch.runs
            ],
            "event_count": len(self.batch.events),
            "telemetry_count": len(self.batch.telemetry),
        }


def run_fault_rehearsal(export_path: Path) -> FaultRehearsalReport:
    """Exercise crash/restart, timeout, blob, disk and provider failures.

    Faults are explicit callback injections; they do not claim to reproduce an
    OS-level kill or a full filesystem fault. The resulting event stream still
    verifies that each condition is retained with a terminal/uncertain status
    rather than being silently converted into success.
    """
    calls = {"worker_crash": 0}

    def worker_crash() -> str:
        calls["worker_crash"] += 1
        if calls["worker_crash"] == 1:
            raise WorkerFailure(
                "injected worker crash with in-flight operation",
                uncertain=True,
                interruption=InterruptionKind.WORKER_RESTART,
            )
        return "recovered_after_same_attempt_resume"

    def timeout() -> None:
        raise TimeoutError("injected campaign deadline")

    def provider_failure() -> None:
        raise WorkerFailure(
            "injected provider outage",
            status=CampaignStatus.PROVIDER_FAILURE,
        )

    def corrupted_blob() -> None:
        raise WorkerFailure("injected corrupted evidence blob", status=CampaignStatus.TOOL_FAILURE)

    def disk_full() -> None:
        raise WorkerFailure("injected disk-full export failure", status=CampaignStatus.TOOL_FAILURE)

    callbacks = {
        "worker_crash": worker_crash,
        "timeout": timeout,
        "corrupted_blob": corrupted_blob,
        "disk_full": disk_full,
        "provider_failure": provider_failure,
    }
    tasks = [WorkerTask(
        name,
        f"fault-{name}-attempt",
        ResourceRequest(name, 1, 1),
        callback,
    ) for name, callback in callbacks.items()]
    batch = WorkerRunner(worker_id="development-fault-rehearsal").run(tasks, resume_uncertain=True)
    batch_events = batch.events
    # ``WorkerBatchReport`` already contains an immutable event snapshot; export
    # it through the runner's shared store to exercise the atomic writer.
    from .events import AppendOnlyEventStore
    store = AppendOnlyEventStore(list(batch_events))
    store.export_jsonl(export_path)
    return FaultRehearsalReport(str(export_path), batch)


__all__ = ["FaultRehearsalReport", "run_fault_rehearsal"]
