"""Verification-stage metrics with explicit campaign-level missingness."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from statistics import mean
from typing import Any, Iterable, Mapping

from .records import CandidateInput, PairKey, VerificationOutcome


class CampaignAvailability(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class VerificationCampaign:
    """All candidate outcomes belonging to one ordered proposal campaign."""

    campaign_id: str
    arm: str
    pair_key: PairKey
    ground_truth: str
    slot_count: int
    outcomes: tuple[VerificationOutcome, ...]
    availability: CampaignAvailability = CampaignAvailability.AVAILABLE
    missing_reason: str | None = None
    model_tag: str = "unknown"
    property_family: str = "unknown"

    def __post_init__(self) -> None:
        if not self.campaign_id or not self.arm or self.slot_count <= 0:
            raise ValueError("verification campaign identity and slot_count are required")
        if not isinstance(self.availability, CampaignAvailability):
            raise ValueError("availability must use CampaignAvailability")
        if self.ground_truth not in {"positive", "negative", "unresolved"}:
            raise ValueError("ground_truth must be positive, negative or unresolved")
        if not isinstance(self.outcomes, tuple):
            raise ValueError("campaign outcomes must be a tuple")
        slot_ids = {(outcome.candidate.campaign_id, outcome.candidate.slot_index) for outcome in self.outcomes}
        if len(slot_ids) != len(self.outcomes):
            raise ValueError("duplicate candidate outcome would double count a slot")
        for outcome in self.outcomes:
            if outcome.candidate.campaign_id != self.campaign_id or outcome.candidate.arm != self.arm or outcome.candidate.pair_key != self.pair_key:
                raise ValueError("candidate outcome does not belong to campaign")
            if outcome.candidate.slot_index >= self.slot_count:
                raise ValueError("candidate outcome slot exceeds campaign slot_count")
        if self.availability is CampaignAvailability.AVAILABLE and self.missing_reason is not None:
            raise ValueError("available campaign cannot have a missing reason")
        if self.availability is not CampaignAvailability.AVAILABLE and not self.missing_reason:
            raise ValueError("unavailable campaign requires a missing reason")

    @property
    def group_key(self) -> str:
        return f"{self.arm}|{self.model_tag}|{self.property_family}"


@dataclass(frozen=True, slots=True)
class VerificationMetric:
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
class VerificationMetrics:
    """Prefix, negative-control and stage metrics for one immutable input set."""

    prefixes: tuple[int, ...]
    groups: tuple[str, ...]
    verified_recall: Mapping[str, Mapping[int, VerificationMetric]]
    false_alert_rate: Mapping[str, VerificationMetric]
    false_discovery_proportion: Mapping[str, VerificationMetric]
    stage_denominators: Mapping[str, Mapping[str, Mapping[str, int]]]
    campaign_count: int
    input_hash: str
    paired_effects: Mapping[str, Mapping[str, tuple[float, ...]]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "record_type": "verification_metrics",
            "prefixes": list(self.prefixes),
            "groups": list(self.groups),
            "verified_recall": {
                group: {str(prefix): metric.as_dict() for prefix, metric in metrics.items()}
                for group, metrics in self.verified_recall.items()
            },
            "false_alert_rate": {group: metric.as_dict() for group, metric in self.false_alert_rate.items()},
            "false_discovery_proportion": {group: metric.as_dict() for group, metric in self.false_discovery_proportion.items()},
            "stage_denominators": {
                group: {stage: dict(statuses) for stage, statuses in stages.items()}
                for group, stages in self.stage_denominators.items()
            },
            "campaign_count": self.campaign_count,
            "input_hash": self.input_hash,
            "paired_effects": {
                contrast: {prefix: list(values) for prefix, values in prefixes.items()}
                for contrast, prefixes in self.paired_effects.items()
            },
        }


def compute_verification_metrics(
    campaigns: Iterable[VerificationCampaign],
    *,
    prefixes: tuple[int, ...] = (1, 2, 4, 8),
    paired_contrasts: tuple[tuple[str, str], ...] = (),
) -> VerificationMetrics:
    """Compute verified prefix recall and negative-control metrics.

    A campaign is a known denominator only when its availability is explicitly
    ``available``.  An absent candidate, provider failure, unsupported binding,
    timeout or crash is therefore not silently converted into a no-alert.
    """

    normalized_prefixes = _prefixes(prefixes)
    rows = tuple(sorted(campaigns, key=lambda row: (row.pair_key, row.arm, row.campaign_id)))
    _validate_campaigns(rows, normalized_prefixes)
    groups = tuple(sorted({row.group_key for row in rows}))
    recall: dict[str, dict[int, VerificationMetric]] = {}
    false_alert: dict[str, VerificationMetric] = {}
    fdp: dict[str, VerificationMetric] = {}
    denominators: dict[str, dict[str, dict[str, int]]] = {}
    for group in groups:
        selected = [row for row in rows if row.group_key == group]
        positive = [row for row in selected if row.ground_truth == "positive"]
        recall[group] = {prefix: _recall_metric(positive, prefix) for prefix in normalized_prefixes}
        negative = [row for row in selected if row.ground_truth == "negative"]
        false_alert[group] = _false_alert_metric(negative, normalized_prefixes[-1])
        fdp[group] = _fdp_metric(selected, normalized_prefixes[-1])
        denominators[group] = _stage_denominators(selected)
    input_hash = _campaign_input_hash(rows, normalized_prefixes)
    paired = _paired_effects(rows, paired_contrasts, normalized_prefixes)
    return VerificationMetrics(normalized_prefixes, groups, recall, false_alert, fdp, denominators, len(rows), input_hash, paired)


def _recall_metric(rows: list[VerificationCampaign], prefix: int) -> VerificationMetric:
    known = [row for row in rows if row.availability is CampaignAvailability.AVAILABLE]
    hits = sum(_verified_hit(row, prefix) for row in known)
    return VerificationMetric(hits / len(known) if known else None, hits, len(known), len(rows), len(rows) - len(known), None if known else "no_available_campaigns")


def _false_alert_metric(rows: list[VerificationCampaign], prefix: int) -> VerificationMetric:
    known = [row for row in rows if row.availability is CampaignAvailability.AVAILABLE]
    hits = sum(_verified_hit(row, prefix) for row in known)
    return VerificationMetric(hits / len(known) if known else None, hits, len(known), len(rows), len(rows) - len(known), None if known else "no_available_negative_controls")


def _fdp_metric(rows: list[VerificationCampaign], prefix: int) -> VerificationMetric:
    known = [row for row in rows if row.availability is CampaignAvailability.AVAILABLE and row.ground_truth in {"positive", "negative"}]
    alerts = [_verified_hit(row, prefix) for row in known]
    false_alerts = sum(alert for row, alert in zip(known, alerts) if row.ground_truth == "negative")
    total_alerts = sum(alerts)
    return VerificationMetric(
        false_alerts / total_alerts if total_alerts else None,
        false_alerts,
        total_alerts,
        len(rows),
        len(rows) - len(known),
        None if total_alerts else "no_verified_alerts",
    )


def _stage_denominators(rows: list[VerificationCampaign]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        counts["campaign"][row.availability.value] += 1
        for outcome in row.outcomes:
            for stage in outcome.stages:
                counts[stage.stage][stage.status.value] += 1
    return {stage: dict(sorted(statuses.items())) for stage, statuses in sorted(counts.items())}


def _verified_hit(row: VerificationCampaign, prefix: int) -> bool:
    return any(outcome.candidate.slot_index < prefix and outcome.verified_finding is True for outcome in row.outcomes)


def _paired_effects(
    rows: tuple[VerificationCampaign, ...],
    contrasts: tuple[tuple[str, str], ...],
    prefixes: tuple[int, ...],
) -> dict[str, dict[str, tuple[float, ...]]]:
    result: dict[str, dict[str, tuple[float, ...]]] = {}
    by_pair: dict[PairKey, dict[str, VerificationCampaign]] = defaultdict(dict)
    for row in rows:
        by_pair[row.pair_key][row.arm] = row
    for left, right in contrasts:
        name = f"{left}-minus-{right}"
        result[name] = {}
        for prefix in prefixes:
            effects: dict[str, list[float]] = defaultdict(list)
            for key, arms in by_pair.items():
                left_row, right_row = arms.get(left), arms.get(right)
                if left_row is None or right_row is None:
                    continue
                if left_row.availability is not CampaignAvailability.AVAILABLE or right_row.availability is not CampaignAvailability.AVAILABLE:
                    continue
                if left_row.ground_truth != right_row.ground_truth:
                    continue
                effects[key.lineage_id].append(float(_verified_hit(left_row, prefix)) - float(_verified_hit(right_row, prefix)))
            result[name][str(prefix)] = tuple(mean(values) for _lineage, values in sorted(effects.items()) if values)
    return result


def _validate_campaigns(rows: tuple[VerificationCampaign, ...], prefixes: tuple[int, ...]) -> None:
    ids = [row.campaign_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate campaign_id would double count verification metrics")
    pair_arms: set[tuple[PairKey, str]] = set()
    for row in rows:
        if any(prefix > row.slot_count for prefix in prefixes):
            raise ValueError(
                f"campaign {row.campaign_id!r} has slot_count {row.slot_count}, "
                f"which is smaller than a requested prefix"
            )
        identity = (row.pair_key, row.arm)
        if identity in pair_arms:
            raise ValueError("duplicate arm for matched pair would invalidate paired metrics")
        pair_arms.add(identity)


def _campaign_input_hash(rows: tuple[VerificationCampaign, ...], prefixes: tuple[int, ...]) -> str:
    from ..contracts.canonical import sha256_hex

    return sha256_hex({
        "prefixes": list(prefixes),
        "campaigns": [
            {
                "campaign_id": row.campaign_id,
                "arm": row.arm,
                "pair_key": row.pair_key.as_dict(),
                "ground_truth": row.ground_truth,
                "slot_count": row.slot_count,
                "availability": row.availability.value,
                "missing_reason": row.missing_reason,
                "model_tag": row.model_tag,
                "property_family": row.property_family,
                "outcomes": [outcome.as_dict() for outcome in row.outcomes],
            }
            for row in rows
        ],
    })


def _prefixes(values: tuple[int, ...]) -> tuple[int, ...]:
    result = tuple(dict.fromkeys(values))
    if not result or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in result):
        raise ValueError("verification prefixes must be positive integers")
    return result


__all__ = [
    "CampaignAvailability", "VerificationCampaign", "VerificationMetric", "VerificationMetrics", "compute_verification_metrics",
]
