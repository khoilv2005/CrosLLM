"""Convert any proposal ``MethodRun`` into shared verification inputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..methods.runner import MethodRun
from .records import CandidateInput, PairKey


def candidates_from_method_run(
    method_run: MethodRun,
    *,
    campaign_id: str,
    pair_key: PairKey,
    arm: str,
) -> tuple[CandidateInput, ...]:
    """Project X/P/T0 slots without changing ordering or raw receipts.

    T0 has no provider response, so its response side is represented by an
    empty mapping.  This is an explicit absence, not a fabricated provider
    success.  Every other method must provide one response per slot.
    """

    if not campaign_id or not arm:
        raise ValueError("campaign_id and arm are required")
    slots = tuple(method_run.slots)
    responses = tuple(method_run.provider_responses)
    if responses and len(responses) != len(slots):
        raise ValueError("method run provider response count must match slot count")
    result: list[CandidateInput] = []
    for index, slot in enumerate(slots):
        slot_row = _as_mapping(slot, "proposal slot")
        declared_index = slot_row.get("index", index)
        if declared_index != index:
            raise ValueError(f"proposal slot {index} has non-canonical index")
        status = slot_row.get("status")
        if hasattr(status, "value"):
            status = status.value
        if not isinstance(status, str) or not status:
            raise ValueError(f"proposal slot {index} has no status")
        response_row = _as_mapping(responses[index], "provider response") if responses else {}
        candidate_payload = slot_row.get("candidate")
        if status != "candidate":
            candidate_payload = None
        result.append(CandidateInput(
            campaign_id=campaign_id,
            attempt_id=method_run.attempt_id,
            pair_key=pair_key,
            arm=arm,
            slot_index=index,
            slot_id=_required_string(slot_row, "slot_id", f"{method_run.attempt_id}:slot:{index}"),
            proposal_status=status,
            canonical_ast_hash=_optional_string(slot_row.get("canonical_ast_hash")),
            raw_response_hash=_optional_string(slot_row.get("raw_response_hash")),
            candidate=candidate_payload,
            raw_response=response_row,
        ))
    return tuple(result)


def _as_mapping(value: object, label: str) -> Mapping[str, Any]:
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _required_string(value: Mapping[str, Any], field: str, fallback: str) -> str:
    item = value.get(field, fallback)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{field} must be a non-empty string")
    return item


def _optional_string(value: object) -> str | None:
    if value is not None and (not isinstance(value, str) or not value):
        raise ValueError("optional hash fields must be non-empty strings")
    return value


__all__ = ["candidates_from_method_run"]
