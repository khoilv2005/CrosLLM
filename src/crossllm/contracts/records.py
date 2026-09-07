"""Small, strict contracts for append-only runtime events.

The runtime can add richer record types later, but these invariants are shared by
campaign, search, replay and adjudication writers from the beginning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    monotonic_seconds: float | None = None
    duration_seconds: float | None = None
    missing_field_reasons: dict[str, str] = field(default_factory=dict)

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
            "monotonic_seconds": self.monotonic_seconds,
            "duration_seconds": self.duration_seconds,
            "missing_field_reasons": self.missing_field_reasons,
        }


def validate_event_log(events: Iterable[EventLog]) -> list[str]:
    """Return invariant violations for an append-only event stream.

    Validation is intentionally pure: callers decide whether to reject, quarantine,
    or report a damaged stream.
    """
    errors: list[str] = []
    seen_events: set[str] = set()
    terminal_attempts: set[str] = set()
    last_monotonic: dict[str, float] = {}
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
        if event.monotonic_seconds is not None:
            previous = last_monotonic.get(event.attempt_id)
            if previous is not None and event.monotonic_seconds < previous:
                errors.append(f"{prefix}: monotonic_seconds moved backwards")
            last_monotonic[event.attempt_id] = event.monotonic_seconds
        if event.duration_seconds is not None and event.duration_seconds < 0:
            errors.append(f"{prefix}: duration_seconds must be non-negative")
        if not isinstance(event.missing_field_reasons, dict):
            errors.append(f"{prefix}: missing_field_reasons must be an object")
        if event.terminal:
            if event.attempt_id in terminal_attempts:
                errors.append(f"{prefix}: duplicate terminal event")
            terminal_attempts.add(event.attempt_id)
    return errors


def validate_foreign_keys(records: Iterable[dict[str, Any]]) -> list[str]:
    """Validate known record-to-record references in a JSONL batch."""
    rows = list(records)
    identifiers: dict[str, set[str]] = {}
    id_fields = {
        "campaign": "campaign_id", "attempt": "attempt_id", "slot": "slot_id",
        "proposal": "proposal_id", "query": "query_id", "witness": "witness_id",
        "finding": "finding_id", "lineage": "lineage_id", "instance": "instance_id",
    }
    for row in rows:
        record_type = row.get("record_type")
        id_field = id_fields.get(record_type)
        if id_field and row.get(id_field):
            identifiers.setdefault(record_type, set()).add(row[id_field])

    references = {
        "campaign": (("instance_id", "instance"), ("lineage_id", "lineage")),
        "attempt": (("campaign_id", "campaign"),),
        "slot": (("campaign_id", "campaign"), ("attempt_id", "attempt")),
        "proposal": (("campaign_id", "campaign"), ("attempt_id", "attempt"), ("slot_id", "slot")),
        "query": (("proposal_id", "proposal"),),
        "witness": (("query_id", "query"),),
        "adjudication": (("finding_id", "finding"),),
    }
    errors: list[str] = []
    for index, row in enumerate(rows, 1):
        for field_name, target_type in references.get(row.get("record_type"), ()):
            value = row.get(field_name)
            if value is not None and value not in identifiers.get(target_type, set()):
                errors.append(f"record {index}: orphan {field_name} {value!r}")
    return errors
