"""Separate proposal-prefix and end-to-end recall endpoints (M07.08).

The prefix endpoint consumes an archived ordered proposal batch only. The
end-to-end endpoint consumes scheduled campaign outcomes under a budget. They
have different denominators and are intentionally represented by different
types so a caller cannot silently pool them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class BatchAvailability(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class RecallMetric:
    value: float | None
    hits: int
    known: int
    total: int
    missing: int
    note: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "hits": self.hits,
            "known": self.known,
            "total": self.total,
            "missing": self.missing,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class ProposalBatch:
    """One stored, ordered proposal sequence for one benchmark instance."""

    batch_id: str
    instance_id: str
    ordered_property_ids: tuple[str, ...]
    gold_property_ids: tuple[str, ...]
    availability: BatchAvailability = BatchAvailability.AVAILABLE
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.batch_id or not self.instance_id:
            raise ValueError("proposal batch identity is required")
        if any(not isinstance(value, str) or not value for value in self.ordered_property_ids):
            raise ValueError("ordered proposal IDs must be non-empty strings")
        if any(not isinstance(value, str) or not value for value in self.gold_property_ids):
            raise ValueError("gold property IDs must be non-empty strings")
        if len(set(self.gold_property_ids)) != len(self.gold_property_ids):
            raise ValueError("gold property IDs must be unique")
        if self.availability is BatchAvailability.AVAILABLE:
            if not self.gold_property_ids or self.missing_reason is not None:
                raise ValueError("available proposal batch requires gold properties and no missing reason")
        elif not self.missing_reason:
            raise ValueError("missing proposal batch requires a reason")


@dataclass(frozen=True, slots=True)
class PrefixRecallResult:
    prefixes: tuple[int, ...]
    metrics: dict[int, RecallMetric]
    endpoint: str = "proposal_prefix_recall"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "endpoint": self.endpoint,
            "prefixes": list(self.prefixes),
            "metrics": {str(prefix): metric.as_dict() for prefix, metric in self.metrics.items()},
            "endpoint_separation": "stored_ordered_proposals_only",
        }


@dataclass(frozen=True, slots=True)
class EndToEndObservation:
    """One scheduled campaign result at a proposal budget."""

    observation_id: str
    instance_id: str
    budget_n: int
    detected: bool | None
    availability: BatchAvailability = BatchAvailability.AVAILABLE
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.observation_id or not self.instance_id or self.budget_n <= 0:
            raise ValueError("end-to-end observation identity and budget are required")
        if self.availability is BatchAvailability.AVAILABLE:
            if self.detected is None or self.missing_reason is not None:
                raise ValueError("available end-to-end observation requires detected boolean")
        elif self.missing_reason is None:
            raise ValueError("missing end-to-end observation requires a reason")


@dataclass(frozen=True, slots=True)
class EndToEndRecallResult:
    budgets: tuple[int, ...]
    metrics: dict[int, RecallMetric]
    endpoint: str = "end_to_end_budget_recall"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "endpoint": self.endpoint,
            "budgets": list(self.budgets),
            "metrics": {str(budget): metric.as_dict() for budget, metric in self.metrics.items()},
            "endpoint_separation": "scheduled_campaign_outcomes_only",
        }


def proposal_prefix_recall(
    batches: Iterable[ProposalBatch],
    *,
    prefixes: tuple[int, ...] = (1, 2, 4, 8),
) -> PrefixRecallResult:
    """Calculate recall@N from stored ordered proposals, never campaign outcomes."""
    normalized_prefixes = _prefixes(prefixes)
    rows = tuple(batches)
    _unique_ids((row.batch_id for row in rows), "proposal batch IDs")
    metrics: dict[int, RecallMetric] = {}
    for prefix in normalized_prefixes:
        known_rows = [row for row in rows if row.availability is BatchAvailability.AVAILABLE]
        hits = sum(bool(set(row.ordered_property_ids[:prefix]) & set(row.gold_property_ids)) for row in known_rows)
        known = len(known_rows)
        metrics[prefix] = RecallMetric(
            hits / known if known else None,
            hits,
            known,
            len(rows),
            len(rows) - known,
            None if known else "no_available_proposal_batches",
        )
    return PrefixRecallResult(normalized_prefixes, metrics)


def end_to_end_budget_recall(
    observations: Iterable[EndToEndObservation],
    *,
    budgets: tuple[int, ...] = (1, 2, 4, 8),
) -> EndToEndRecallResult:
    """Calculate recall by scheduled budget; does not inspect proposal ordering."""
    normalized_budgets = _prefixes(budgets)
    rows = tuple(observations)
    _unique_ids((row.observation_id for row in rows), "end-to-end observation IDs")
    if any(row.budget_n not in normalized_budgets for row in rows):
        raise ValueError("observation budget is outside the requested endpoint")
    metrics: dict[int, RecallMetric] = {}
    for budget in normalized_budgets:
        selected = [row for row in rows if row.budget_n == budget]
        known_rows = [row for row in selected if row.availability is BatchAvailability.AVAILABLE]
        hits = sum(row.detected is True for row in known_rows)
        known = len(known_rows)
        metrics[budget] = RecallMetric(
            hits / known if known else None,
            hits,
            known,
            len(selected),
            len(selected) - known,
            "no_scheduled_observations" if not selected else ("no_available_observations" if not known else None),
        )
    return EndToEndRecallResult(normalized_budgets, metrics)


def _prefixes(values: tuple[int, ...]) -> tuple[int, ...]:
    result = tuple(dict.fromkeys(values))
    if not result or any(value <= 0 for value in result):
        raise ValueError("prefix/budget values must be positive")
    return result


def _unique_ids(values: Iterable[str], label: str) -> None:
    identifiers = tuple(values)
    if any(not identifier for identifier in identifiers) or len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{label} must be unique and non-empty")


__all__ = [
    "BatchAvailability", "EndToEndObservation", "EndToEndRecallResult",
    "PrefixRecallResult", "ProposalBatch", "RecallMetric",
    "end_to_end_budget_recall", "proposal_prefix_recall",
]
