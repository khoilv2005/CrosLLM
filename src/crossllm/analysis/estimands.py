"""M09 estimands over frozen raw campaign outcomes.

The implementation keeps unavailable fields explicit and performs hierarchy-aware
aggregation before any pooled summaries. It is intentionally independent of the
synthetic benchmark files currently in the repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from statistics import mean
from typing import Any, Iterable


class OutcomeAvailability(StrEnum):
    AVAILABLE = "available"
    PROVIDER_FAILURE = "provider_failure"
    TIMEOUT = "timeout"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CampaignOutcome:
    """One raw campaign-level observation.

    Boolean endpoints may be ``None`` when the relevant stage did not produce a
    measurement. This is retained as missingness, never silently converted to
    either success or zero.
    """

    campaign_id: str
    instance_id: str
    lineage_id: str
    method: str
    replicate: int
    ground_truth: str
    detected: bool | None = None
    useful_proposal: bool | None = None
    claim_emitted: bool | None = None
    correct_claim: bool | None = None
    native_witness: bool | None = None
    independent_replay: bool | None = None
    claim_time_seconds: float | None = None
    witness_time_seconds: float | None = None
    horizon_seconds: float = 1.0
    availability: OutcomeAvailability = OutcomeAvailability.AVAILABLE
    first_failure: str | None = None

    def __post_init__(self) -> None:
        if not all((self.campaign_id, self.instance_id, self.lineage_id, self.method)):
            raise ValueError("campaign identity fields are required")
        if self.replicate <= 0:
            raise ValueError("replicate must be positive")
        if self.ground_truth not in {"positive", "negative", "unresolved"}:
            raise ValueError("ground_truth must be positive, negative or unresolved")
        if not isinstance(self.availability, OutcomeAvailability):
            raise ValueError("availability must use OutcomeAvailability")
        if self.horizon_seconds <= 0 or not isfinite(self.horizon_seconds):
            raise ValueError("horizon_seconds must be finite and positive")
        for name in ("claim_time_seconds", "witness_time_seconds"):
            value = getattr(self, name)
            if value is not None and (value < 0 or not isfinite(value)):
                raise ValueError(f"{name} must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class Metric:
    value: float | None
    known: int
    total: int
    missing: int
    note: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "known": self.known,
            "total": self.total,
            "missing": self.missing,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class TimeEndpoint:
    """Restricted, availability-conditioned and descriptive survival outputs."""

    restricted: Metric
    availability_conditioned: Metric
    intention_to_run: Metric
    kaplan_meier: tuple[dict[str, float | int], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "restricted": self.restricted.as_dict(),
            "availability_conditioned": self.availability_conditioned.as_dict(),
            "intention_to_run": self.intention_to_run.as_dict(),
            "kaplan_meier": [dict(row) for row in self.kaplan_meier],
        }


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    methods: tuple[str, ...]
    recall: dict[str, Metric]
    useful_proposal_recall: dict[str, Metric]
    false_alert_rate: dict[str, Metric]
    false_discovery_proportion: dict[str, Metric]
    native_witness_yield: dict[str, Metric]
    independent_replay_rate: dict[str, Metric]
    witness_time: dict[str, Metric]
    claim_time: dict[str, Metric]
    paired_effects: dict[str, tuple[float, ...]]
    stage_denominators: dict[str, dict[str, dict[str, int]]]
    time_details: dict[str, dict[str, TimeEndpoint]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "methods": list(self.methods),
            "recall": {key: value.as_dict() for key, value in self.recall.items()},
            "useful_proposal_recall": {key: value.as_dict() for key, value in self.useful_proposal_recall.items()},
            "false_alert_rate": {key: value.as_dict() for key, value in self.false_alert_rate.items()},
            "false_discovery_proportion": {key: value.as_dict() for key, value in self.false_discovery_proportion.items()},
            "native_witness_yield": {key: value.as_dict() for key, value in self.native_witness_yield.items()},
            "independent_replay_rate": {key: value.as_dict() for key, value in self.independent_replay_rate.items()},
            "witness_time": {key: value.as_dict() for key, value in self.witness_time.items()},
            "claim_time": {key: value.as_dict() for key, value in self.claim_time.items()},
            "paired_effects": {key: list(value) for key, value in self.paired_effects.items()},
            "stage_denominators": self.stage_denominators,
            "time_details": {
                method: {field: endpoint.as_dict() for field, endpoint in details.items()}
                for method, details in self.time_details.items()
            },
        }


def analyze_outcomes(outcomes: Iterable[CampaignOutcome], *, compare_methods: tuple[str, str] | None = None) -> AnalysisReport:
    rows = sorted(outcomes, key=lambda row: (row.lineage_id, row.instance_id, row.method, row.replicate, row.campaign_id))
    _validate_unique_campaigns(rows)
    methods = tuple(sorted({row.method for row in rows}))
    recall = {method: _hierarchical_binary(rows, method, "positive", "detected") for method in methods}
    useful = {method: _hierarchical_binary(rows, method, "positive", "useful_proposal") for method in methods}
    false_alert = {method: _hierarchical_binary(rows, method, "negative", "claim_emitted") for method in methods}
    fdp = {method: _false_discovery(rows, method) for method in methods}
    witness = {method: _hierarchical_binary(rows, method, "positive", "native_witness") for method in methods}
    replay = {method: _hierarchical_binary(rows, method, "positive", "independent_replay") for method in methods}
    witness_time = {method: _hierarchical_time(rows, method, "witness_time_seconds") for method in methods}
    claim_time = {method: _hierarchical_time(rows, method, "claim_time_seconds") for method in methods}
    time_details = {
        method: {
            "witness_time": _time_endpoint(rows, method, "witness_time_seconds"),
            "claim_time": _time_endpoint(rows, method, "claim_time_seconds"),
        }
        for method in methods
    }
    paired_effects: dict[str, tuple[float, ...]] = {}
    if compare_methods is not None:
        left, right = compare_methods
        if left not in methods or right not in methods:
            raise ValueError("compare_methods must be present in outcomes")
        paired_effects[f"{left}-minus-{right}"] = tuple(_paired_lineage_effects(rows, left, right))
    stage_denominators = {method: _stage_denominators(rows, method) for method in methods}
    return AnalysisReport(
        methods, recall, useful, false_alert, fdp, witness, replay,
        witness_time, claim_time, paired_effects, stage_denominators, time_details,
    )


def _validate_unique_campaigns(rows: list[CampaignOutcome]) -> None:
    ids = [row.campaign_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate campaign_id would double count a raw outcome")


def _hierarchical_binary(rows: list[CampaignOutcome], method: str, truth: str, field: str) -> Metric:
    selected = [row for row in rows if row.method == method and row.ground_truth == truth]
    total = len(selected)
    known_by_instance: dict[tuple[str, str], list[float]] = {}
    for row in selected:
        value = getattr(row, field)
        if value is not None:
            known_by_instance.setdefault((row.lineage_id, row.instance_id), []).append(float(value))
    instance_means = {key: mean(values) for key, values in known_by_instance.items()}
    by_lineage: dict[str, list[float]] = {}
    for (lineage, _instance), value in instance_means.items():
        by_lineage.setdefault(lineage, []).append(value)
    lineage_means = [mean(values) for _lineage, values in sorted(by_lineage.items())]
    return Metric(
        value=mean(lineage_means) if lineage_means else None,
        known=sum(len(values) for values in known_by_instance.values()),
        total=total,
        missing=total - sum(len(values) for values in known_by_instance.values()),
        note=None if lineage_means else "no_known_measurements",
    )


def _false_discovery(rows: list[CampaignOutcome], method: str) -> Metric:
    selected = [row for row in rows if row.method == method and row.ground_truth == "negative"]
    claims = [row for row in selected if row.claim_emitted is True]
    known = [row for row in claims if row.correct_claim is not None]
    false_claims = [row for row in known if row.correct_claim is False]
    return Metric(
        value=(len(false_claims) / len(known)) if known else None,
        known=len(known),
        total=len(claims),
        missing=len(claims) - len(known),
        note="precision_NA_no_claims" if not claims else None,
    )


def _hierarchical_time(rows: list[CampaignOutcome], method: str, field: str) -> Metric:
    return _time_endpoint(rows, method, field).restricted


def _time_endpoint(rows: list[CampaignOutcome], method: str, field: str) -> TimeEndpoint:
    selected = [row for row in rows if row.method == method and row.ground_truth == "positive"]
    if not selected:
        empty = Metric(None, 0, 0, 0, "no_positive_rows")
        return TimeEndpoint(empty, empty, empty, ())
    scores_by_instance: dict[tuple[str, str], list[float]] = {}
    for row in selected:
        value = getattr(row, field)
        # The protocol's restricted score censors no-event, timeout and crash at
        # tau. We retain availability separately in stage denominators.
        score = row.horizon_seconds if value is None else min(value, row.horizon_seconds)
        scores_by_instance.setdefault((row.lineage_id, row.instance_id), []).append(score)
    by_lineage: dict[str, list[float]] = {}
    for (lineage, _instance), values in scores_by_instance.items():
        by_lineage.setdefault(lineage, []).append(mean(values))
    lineage_means = [mean(values) for _lineage, values in sorted(by_lineage.items())]
    known = sum(1 for row in selected if getattr(row, field) is not None)
    restricted = Metric(mean(lineage_means), known, len(selected), len(selected) - known, "censored_at_horizon")

    available = [row for row in selected if row.availability is OutcomeAvailability.AVAILABLE]
    conditioned_scores_by_instance: dict[tuple[str, str], list[float]] = {}
    for row in available:
        value = getattr(row, field)
        score = row.horizon_seconds if value is None else min(value, row.horizon_seconds)
        conditioned_scores_by_instance.setdefault((row.lineage_id, row.instance_id), []).append(score)
    conditioned_by_lineage: dict[str, list[float]] = {}
    for (lineage, _instance), values in conditioned_scores_by_instance.items():
        conditioned_by_lineage.setdefault(lineage, []).append(mean(values))
    conditioned_lineages = [mean(values) for _lineage, values in sorted(conditioned_by_lineage.items())]
    conditioned_known = sum(1 for row in available if getattr(row, field) is not None)
    conditioned = Metric(
        mean(conditioned_lineages) if conditioned_lineages else None,
        conditioned_known,
        len(available),
        len(available) - conditioned_known,
        "availability_conditioned" if conditioned_lineages else "no_available_rows",
    )
    intention = Metric(
        len(available) / len(selected),
        len(selected),
        len(selected),
        0,
        "available_execution_fraction",
    )
    return TimeEndpoint(restricted, conditioned, intention, _kaplan_meier(selected, field))


def _kaplan_meier(rows: list[CampaignOutcome], field: str) -> tuple[dict[str, float | int], ...]:
    observations: list[tuple[float, bool]] = []
    for row in rows:
        value = getattr(row, field)
        event = value is not None and row.availability is OutcomeAvailability.AVAILABLE and value <= row.horizon_seconds
        time = min(value, row.horizon_seconds) if value is not None else row.horizon_seconds
        observations.append((time, event))
    survival = 1.0
    result: list[dict[str, float | int]] = []
    for time in sorted({time for time, _event in observations}):
        at_risk = sum(observed_time >= time for observed_time, _event in observations)
        events = sum(observed_time == time and event for observed_time, event in observations)
        if at_risk > 0:
            survival *= (1 - events / at_risk)
        result.append({"time": time, "at_risk": at_risk, "events": events, "survival": survival})
    return tuple(result)


def _paired_lineage_effects(rows: list[CampaignOutcome], left: str, right: str) -> list[float]:
    # Pair at the prespecified replicate unit first.  Averaging all replicates
    # inside each method before matching would let an unmatched successful arm
    # influence the effect and would violate the paired design.
    per_replicate: dict[tuple[str, str, int], dict[str, float]] = {}
    for row in rows:
        if row.ground_truth != "positive" or row.method not in {left, right} or row.detected is None:
            continue
        key = (row.lineage_id, row.instance_id, row.replicate)
        per_replicate.setdefault(key, {})[row.method] = float(row.detected)
    per_instance: dict[tuple[str, str], list[float]] = {}
    for (lineage, instance, _replicate), values in sorted(per_replicate.items()):
        if left in values and right in values:
            per_instance.setdefault((lineage, instance), []).append(values[left] - values[right])
    by_lineage: dict[str, list[float]] = {}
    for (lineage, _instance), values in sorted(per_instance.items()):
        by_lineage.setdefault(lineage, []).append(mean(values))
    return [mean(values) for _lineage, values in sorted(by_lineage.items())]


def _stage_denominators(rows: list[CampaignOutcome], method: str) -> dict[str, dict[str, int]]:
    selected = [row for row in rows if row.method == method]
    stages = {
        "detected": lambda row: row.detected,
        "useful_proposal": lambda row: row.useful_proposal,
        "native_witness": lambda row: row.native_witness,
        "independent_replay": lambda row: row.independent_replay,
        "claim_emitted": lambda row: row.claim_emitted,
    }
    result: dict[str, dict[str, int]] = {}
    for name, getter in stages.items():
        known = sum(getter(row) is not None for row in selected)
        result[name] = {
            "total": len(selected),
            "known": known,
            "missing": len(selected) - known,
            "positive": sum(getter(row) is True for row in selected),
        }
    availability: dict[str, int] = {}
    for row in selected:
        availability[row.availability.value] = availability.get(row.availability.value, 0) + 1
    result["availability"] = availability
    return result
