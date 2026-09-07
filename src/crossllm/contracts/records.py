"""Small, strict contracts for append-only runtime events.

The runtime can add richer record types later, but these invariants are shared by
campaign, search, replay and adjudication writers from the beginning.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable


class CampaignStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    UNSUPPORTED = "unsupported"
    PROVIDER_FAILURE = "provider_failure"
    TOOL_FAILURE = "tool_failure"
    NO_VALID_PROPOSAL = "no_valid_proposal"


class SearchStatus(StrEnum):
    SAT = "sat"
    BOUNDED_UNSAT = "bounded_unsat"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNSUPPORTED = "unsupported"
    CRASH = "crash"


class ReplayStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


class AdjudicationStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class EventLog:
    """One immutable event with explicit IDs and a schema version."""

    event_id: str
    event_type: str
    campaign_id: str
    attempt_id: str
    timestamp: str
    payload: dict[str, Any]
    schema_version: int = 1
    terminal: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "campaign_id": self.campaign_id,
            "attempt_id": self.attempt_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "terminal": self.terminal,
        }


def validate_event_log(events: Iterable[EventLog]) -> list[str]:
    """Return invariant violations for an append-only event stream.

    Validation is intentionally pure: callers decide whether to reject, quarantine,
    or report a damaged stream.
    """
    errors: list[str] = []
    seen_events: set[str] = set()
    terminal_attempts: set[str] = set()
    for index, event in enumerate(events, 1):
        prefix = f"event {index}"
        if event.schema_version != 1:
            errors.append(f"{prefix}: unsupported schema_version")
        if not event.event_id:
            errors.append(f"{prefix}: missing event_id")
        elif event.event_id in seen_events:
            errors.append(f"{prefix}: duplicate event_id")
        seen_events.add(event.event_id)
        if not event.event_type:
            errors.append(f"{prefix}: missing event_type")
        if not event.campaign_id or not event.attempt_id:
            errors.append(f"{prefix}: missing campaign or attempt ID")
        if not event.timestamp:
            errors.append(f"{prefix}: missing timestamp")
        if not isinstance(event.payload, dict):
            errors.append(f"{prefix}: payload must be an object")
        if event.terminal:
            if event.attempt_id in terminal_attempts:
                errors.append(f"{prefix}: duplicate terminal event")
            terminal_attempts.add(event.attempt_id)
    return errors
