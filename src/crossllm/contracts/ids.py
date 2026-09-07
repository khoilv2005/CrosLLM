"""Identifiers shared by campaign records and append-only events."""

from __future__ import annotations

from uuid import UUID, uuid4


def new_id() -> str:
    """Create a UUID4 string for a new persisted record."""
    return str(uuid4())


def require_id(value: str, field_name: str = "id") -> str:
    """Validate and return a UUID string used as a persisted foreign key."""
    try:
        UUID(value)
    except (ValueError, AttributeError, TypeError) as error:
        raise ValueError(f"{field_name} must be a UUID") from error
    return value
