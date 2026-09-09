"""Normalized runtime events for one method run (M06/M08).

The provider and proposal objects retain the detailed archive.  This module
projects them into append-only runtime events so a campaign export can be
audited without reconstructing method state from an opaque aggregate report.
Sensitive transport credentials are never part of the projection.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..contracts import EventLog
from ..contracts.ids import new_id
from ..methods import MethodRun
from .events import AppendOnlyEventStore


_FORBIDDEN_KEYS = frozenset({
    "api_key",
    "ollama_api_key",
    "authorization",
    "bearer_token",
})


def _assert_no_secret_fields(value: Any) -> None:
    """Reject credential-shaped fields before they enter an event payload."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if isinstance(key, str) and key.lower() in _FORBIDDEN_KEYS:
                raise ValueError("method runtime events cannot archive provider credentials")
            _assert_no_secret_fields(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _assert_no_secret_fields(nested)


def append_method_run_events(
    store: AppendOnlyEventStore,
    method_run: MethodRun,
    *,
    campaign_id: str,
    timestamp: str,
    event_id_factory: Callable[[], str] = new_id,
) -> int:
    """Append start, provider, slot and completion events for ``method_run``.

    Provider responses and proposal slots are emitted as separate events. This
    preserves the one-response/one-slot correspondence and makes failures,
    duplicates and consumed slots visible in the append-only stream. The
    function returns the number of events appended.
    """
    if not campaign_id or not timestamp:
        raise ValueError("campaign_id and timestamp are required")
    if not callable(event_id_factory):
        raise ValueError("event_id_factory must be callable")
    if len(method_run.provider_responses) != len(method_run.slots):
        raise ValueError("method run must have one provider response per proposal slot")

    metadata = {
        "track": method_run.track.value,
        "backbone": method_run.backbone,
        "attempt_id": method_run.attempt_id,
        "template_hash": method_run.template_hash,
        "artifact_pack_hash": method_run.artifact_pack_hash,
        "settings": dict(method_run.settings),
    }
    _assert_no_secret_fields(metadata)

    count = 0

    def append(event_type: str, payload: dict[str, object]) -> None:
        nonlocal count
        _assert_no_secret_fields(payload)
        store.append(EventLog(
            event_id=event_id_factory(),
            event_type=event_type,
            campaign_id=campaign_id,
            attempt_id=method_run.attempt_id,
            timestamp=timestamp,
            payload=payload,
        ))
        count += 1

    append("method_started", metadata)
    for index, (slot, response) in enumerate(zip(method_run.slots, method_run.provider_responses)):
        slot_payload = slot.as_dict() if hasattr(slot, "as_dict") else slot
        response_payload = response.as_dict() if hasattr(response, "as_dict") else response
        append("provider_response", {
            "track": method_run.track.value,
            "slot_index": index,
            "response": response_payload,
        })
        append("proposal_slot_recorded", {
            "track": method_run.track.value,
            "slot_index": index,
            "slot": slot_payload,
        })
    append("method_completed", {
        **metadata,
        "slot_count": len(method_run.slots),
        "provider_call_count": len(method_run.provider_responses),
        "token_measurement_count": len(method_run.token_measurements),
        "budget_check_count": len(method_run.budget_checks),
    })
    return count


__all__ = ["append_method_run_events"]
