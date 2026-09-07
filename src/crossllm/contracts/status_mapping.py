"""Versioned serialization of independent runtime status dimensions."""

from __future__ import annotations

from typing import Any

from .records import AdjudicationStatus, CampaignStatus, ReplayStatus, SearchStatus

STATUS_MAPPING_VERSION = 1


def serialize_statuses(
    campaign_status: CampaignStatus,
    search_status: SearchStatus | None = None,
    replay_status: ReplayStatus | None = None,
    adjudication_status: AdjudicationStatus | None = None,
) -> dict[str, Any]:
    """Serialize independent status dimensions without collapsing information."""
    return {
        "status_mapping_version": STATUS_MAPPING_VERSION,
        "campaign_status": campaign_status.value,
        "search_status": search_status.value if search_status is not None else None,
        "replay_status": replay_status.value if replay_status is not None else None,
        "adjudication_status": (
            adjudication_status.value if adjudication_status is not None else None
        ),
    }


def validate_statuses(record: dict[str, Any]) -> list[str]:
    """Validate a serialized status record and preserve unknown-state semantics."""
    errors: list[str] = []
    if record.get("status_mapping_version") != STATUS_MAPPING_VERSION:
        errors.append("unsupported status_mapping_version")
    enum_fields = (
        ("campaign_status", CampaignStatus),
        ("search_status", SearchStatus),
        ("replay_status", ReplayStatus),
        ("adjudication_status", AdjudicationStatus),
    )
    for field, enum_type in enum_fields:
        value = record.get(field)
        if value is None and field != "campaign_status":
            continue
        try:
            enum_type(value)
        except (TypeError, ValueError):
            errors.append(f"invalid {field}: {value!r}")
    return errors
