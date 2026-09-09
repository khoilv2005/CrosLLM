"""Append-only runtime events and campaign state transitions for M08.03."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import json
import os
from pathlib import Path
from threading import RLock
from typing import Callable

from ..contracts import CampaignStatus, EventLog, validate_event_log
from ..contracts.ids import new_id


class AttemptState:
    PLANNED = "planned"
    RUNNING = "running"
    UNCERTAIN = "uncertain"
    TERMINAL = "terminal"


class InterruptionKind(StrEnum):
    WORKER_RESTART = "worker_restart"
    LOST_RESPONSE = "lost_response"
    PROVIDER_OUTAGE = "provider_outage"
    VERSION_DRIFT = "version_drift"


class ResumeAction(StrEnum):
    RESUME_SAME_ATTEMPT = "resume_same_attempt"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class ResumePolicy:
    """Fixed interruption policy; it is part of runtime provenance."""

    worker_restart: ResumeAction = ResumeAction.RESUME_SAME_ATTEMPT
    lost_response: ResumeAction = ResumeAction.RESUME_SAME_ATTEMPT
    provider_outage: ResumeAction = ResumeAction.RESUME_SAME_ATTEMPT
    version_drift: ResumeAction = ResumeAction.BLOCK

    def __post_init__(self) -> None:
        if self.version_drift != ResumeAction.BLOCK:
            raise ValueError("version drift must block same-attempt resume")

    def action_for(self, kind: InterruptionKind) -> ResumeAction:
        return {
            InterruptionKind.WORKER_RESTART: self.worker_restart,
            InterruptionKind.LOST_RESPONSE: self.lost_response,
            InterruptionKind.PROVIDER_OUTAGE: self.provider_outage,
            InterruptionKind.VERSION_DRIFT: self.version_drift,
        }[kind]


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    campaign_id: str
    attempt_id: str
    state: str
    campaign_status: CampaignStatus
    terminal: bool
    event_count: int


class AppendOnlyEventStore:
    """In-memory append-only store with deterministic JSONL export."""

    def __init__(self, events: list[EventLog] | None = None) -> None:
        self._lock = RLock()
        self._events: list[EventLog] = []
        self._event_ids: set[str] = set()
        self._terminal_attempts: set[str] = set()
        for event in events or []:
            self.append(event)

    @property
    def events(self) -> tuple[EventLog, ...]:
        with self._lock:
            return tuple(self._events)

    def append(self, event: EventLog) -> None:
        with self._lock:
            if event.event_id in self._event_ids:
                raise ValueError("duplicate event_id")
            if event.terminal and event.attempt_id in self._terminal_attempts:
                raise ValueError("duplicate terminal event for attempt")
            candidate = [*self._events, event]
            errors = validate_event_log(candidate)
            if errors:
                raise ValueError(errors[0])
            self._commit(candidate, event)

    def _commit(self, candidate: list[EventLog], event: EventLog) -> None:
        """Commit a validated candidate stream.

        Subclasses may persist the complete candidate before the in-memory
        indexes are advanced.  That ordering prevents a failed disk write from
        making the live state claim an event which was never durably recorded.
        """
        self._persist_candidate(candidate)
        self._events.append(event)
        self._event_ids.add(event.event_id)
        if event.terminal:
            self._terminal_attempts.add(event.attempt_id)

    def _persist_candidate(self, events: list[EventLog]) -> None:
        """Hook for durable stores; the default store remains memory-only."""

    def export_jsonl(self, path: Path) -> None:
        # A complete temporary file prevents a reader from observing a partial
        # terminal record after a process interruption.  ``replace`` is atomic
        # on the same filesystem and repeated exports are byte-identical.
        with self._lock:
            self._write_jsonl_atomic(path, self._events)

    @staticmethod
    def _write_jsonl_atomic(path: Path, events: list[EventLog] | tuple[EventLog, ...]) -> None:
        """Replace a JSONL snapshot without exposing a partial record."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        payload = "".join(json.dumps(event.as_dict(), sort_keys=True) + "\n" for event in events)
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            # A failed replace must not leave a misleading durable-looking
            # temporary event log behind for a later restart.
            if temporary.exists():
                temporary.unlink()

    @classmethod
    def load_jsonl(cls, path: Path) -> "AppendOnlyEventStore":
        """Load and validate an event stream without silently repairing it."""
        events: list[EventLog] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                required = {
                    "schema_version", "event_id", "event_type", "campaign_id", "attempt_id",
                    "timestamp", "payload", "terminal", "missing_field_reasons",
                }
                missing = sorted(required - set(row))
                if missing:
                    raise ValueError(f"missing fields: {', '.join(missing)}")
                events.append(EventLog(
                    event_id=row["event_id"],
                    event_type=row["event_type"],
                    campaign_id=row["campaign_id"],
                    attempt_id=row["attempt_id"],
                    timestamp=row["timestamp"],
                    payload=row["payload"],
                    schema_version=row["schema_version"],
                    terminal=row["terminal"],
                    monotonic_seconds=row.get("monotonic_seconds"),
                    duration_seconds=row.get("duration_seconds"),
                    missing_field_reasons=row["missing_field_reasons"],
                ))
            except (TypeError, ValueError, json.JSONDecodeError, KeyError) as exc:
                raise ValueError(f"invalid event JSONL at line {line_number}: {exc}") from exc
        return cls(events)


class PersistentEventStore(AppendOnlyEventStore):
    """Append-only event store that commits every event to an atomic JSONL file.

    The file is the recovery boundary: an existing stream is loaded and fully
    validated before the store can be used.  Corruption is rejected rather than
    truncated or silently repaired.  Each append rewrites a complete snapshot
    to a same-directory temporary file, flushes it, and atomically replaces the
    target, so a process interruption cannot create a half-written terminal
    record.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if self.path.exists() and not self.path.is_file():
            raise ValueError("persistent event path must be a regular file")
        if self.path.exists():
            loaded = AppendOnlyEventStore.load_jsonl(self.path)
            initial = list(loaded.events)
        else:
            initial = []
        self._loading = True
        super().__init__()
        for event in initial:
            self.append(event)
        self._loading = False

    def _persist_candidate(self, events: list[EventLog]) -> None:
        if not self._loading:
            self._write_jsonl_atomic(self.path, events)

    def flush(self) -> None:
        """Materialize the current stream, useful after external path setup."""
        with self._lock:
            self._write_jsonl_atomic(self.path, self._events)


class CampaignStateMachine:
    """One campaign attempt with explicit interruption and terminal policy."""

    _terminal_statuses = {
        CampaignStatus.COMPLETED,
        CampaignStatus.TIMEOUT,
        CampaignStatus.UNSUPPORTED,
        CampaignStatus.PROVIDER_FAILURE,
        CampaignStatus.TOOL_FAILURE,
        CampaignStatus.NO_VALID_PROPOSAL,
    }

    def __init__(
        self,
        campaign_id: str,
        attempt_id: str,
        store: AppendOnlyEventStore,
        *,
        clock: Callable[[], float] | None = None,
        timestamp: Callable[[], str] | None = None,
        policy: ResumePolicy | None = None,
    ) -> None:
        if not campaign_id or not attempt_id:
            raise ValueError("campaign_id and attempt_id are required")
        self.campaign_id = campaign_id
        self.attempt_id = attempt_id
        self.store = store
        self._clock = clock or __import__("time").monotonic
        self._timestamp = timestamp or (lambda: datetime.now(timezone.utc).isoformat())
        self.policy = policy or ResumePolicy()
        self.state = AttemptState.PLANNED
        self.campaign_status = CampaignStatus.PLANNED
        self._last_monotonic = -1.0
        self._last_interruption: InterruptionKind | None = None

    def snapshot(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            self.campaign_id,
            self.attempt_id,
            self.state,
            self.campaign_status,
            self.state == AttemptState.TERMINAL,
            len(self.store.events),
        )

    def start(self, payload: dict[str, object] | None = None) -> None:
        if self.state != AttemptState.PLANNED:
            raise ValueError("attempt cannot start from current state")
        self._start(payload or {})

    def _start(self, payload: dict[str, object]) -> None:
        self._append("campaign_started", payload, terminal=False)
        self.state = AttemptState.RUNNING
        self.campaign_status = CampaignStatus.RUNNING

    def mark_uncertain(
        self,
        reason: str,
        interruption: InterruptionKind = InterruptionKind.WORKER_RESTART,
    ) -> None:
        if self.state != AttemptState.RUNNING:
            raise ValueError("only a running attempt can become uncertain")
        if not reason:
            raise ValueError("uncertain state requires a reason")
        self._append(
            "attempt_uncertain",
            {"reason": reason, "interruption": interruption.value},
            terminal=False,
        )
        self.state = AttemptState.UNCERTAIN
        self._last_interruption = interruption

    def finish(self, status: CampaignStatus, payload: dict[str, object] | None = None) -> None:
        if status not in self._terminal_statuses:
            raise ValueError("finish requires a terminal campaign status")
        if self.state not in {AttemptState.RUNNING, AttemptState.UNCERTAIN}:
            raise ValueError("attempt is already terminal or was never started")
        self._append("campaign_terminal", {"status": status, **(payload or {})}, terminal=True)
        self.state = AttemptState.TERMINAL
        self.campaign_status = status

    def resume(self, interruption: InterruptionKind | None = None) -> None:
        if self.state != AttemptState.UNCERTAIN:
            if self.state == AttemptState.TERMINAL:
                raise ValueError("attempt is terminal and cannot resume")
            raise ValueError("only an uncertain attempt can resume")
        interruption = interruption or self._last_interruption or InterruptionKind.WORKER_RESTART
        if self.policy.action_for(interruption) != ResumeAction.RESUME_SAME_ATTEMPT:
            raise ValueError(f"resume blocked by policy for {interruption.value}")
        self._start({"resumed": True, "same_attempt_id": True})

    @classmethod
    def restore(
        cls,
        campaign_id: str,
        attempt_id: str,
        store: AppendOnlyEventStore,
        *,
        clock: Callable[[], float] | None = None,
        timestamp: Callable[[], str] | None = None,
        policy: ResumePolicy | None = None,
    ) -> "CampaignStateMachine":
        """Reconstruct lifecycle state after process restart from immutable events."""
        machine = cls(campaign_id, attempt_id, store, clock=clock, timestamp=timestamp, policy=policy)
        selected = [
            event for event in store.events
            if event.campaign_id == campaign_id and event.attempt_id == attempt_id
        ]
        if not selected:
            raise ValueError("no events found for campaign attempt")
        for event in selected:
            if event.monotonic_seconds is not None:
                machine._last_monotonic = max(machine._last_monotonic, event.monotonic_seconds)
            if event.event_type == "campaign_started":
                if machine.state not in {AttemptState.PLANNED, AttemptState.UNCERTAIN}:
                    raise ValueError("invalid campaign_started lifecycle")
                machine.state = AttemptState.RUNNING
                machine.campaign_status = CampaignStatus.RUNNING
            elif event.event_type == "attempt_uncertain":
                if machine.state != AttemptState.RUNNING:
                    raise ValueError("invalid attempt_uncertain lifecycle")
                machine.state = AttemptState.UNCERTAIN
                try:
                    machine._last_interruption = InterruptionKind(event.payload["interruption"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError("uncertain event has invalid interruption kind") from exc
            elif event.event_type == "campaign_terminal":
                if machine.state not in {AttemptState.RUNNING, AttemptState.UNCERTAIN}:
                    raise ValueError("invalid campaign_terminal lifecycle")
                try:
                    status = CampaignStatus(event.payload["status"])
                except (KeyError, ValueError, TypeError) as exc:
                    raise ValueError("terminal event has invalid campaign status") from exc
                machine.state = AttemptState.TERMINAL
                machine.campaign_status = status
        if machine.state == AttemptState.PLANNED:
            raise ValueError("campaign attempt has no start event")
        return machine

    def _append(self, event_type: str, payload: dict[str, object], *, terminal: bool) -> None:
        monotonic = self._clock()
        if monotonic < self._last_monotonic:
            raise ValueError("runtime clock moved backwards")
        self._last_monotonic = monotonic
        self.store.append(
            EventLog(
                event_id=new_id(),
                event_type=event_type,
                campaign_id=self.campaign_id,
                attempt_id=self.attempt_id,
                timestamp=self._timestamp(),
                payload=payload,
                terminal=terminal,
                monotonic_seconds=monotonic,
            )
        )
