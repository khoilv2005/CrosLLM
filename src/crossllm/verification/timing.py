"""Separate proposal and verification timing/token observations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import isfinite

from ..methods.runner import MethodRun
from .records import VerificationOutcome


@dataclass(frozen=True, slots=True)
class TimingObservation:
    """An aggregate with an explicit known/missing denominator."""

    value: int | float | None
    known: int
    total: int
    missing: int
    unit: str
    source: str
    note: str | None = None

    def __post_init__(self) -> None:
        if self.known < 0 or self.total < 0 or self.missing < 0 or self.known + self.missing != self.total:
            raise ValueError("timing observation denominators are inconsistent")
        if not self.unit or not self.source:
            raise ValueError("timing observation unit and source are required")
        if self.value is not None:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)) or not isfinite(float(self.value)) or self.value < 0:
                raise ValueError("timing observation value must be finite and non-negative")
            if self.missing:
                raise ValueError("an aggregate value cannot be present when observations are missing")

    def as_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "known": self.known,
            "total": self.total,
            "missing": self.missing,
            "unit": self.unit,
            "source": self.source,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class MethodTiming:
    """Timing/token projection for one method run and its verified stages."""

    track: str
    backbone: str
    attempt_id: str
    slot_count: int
    proposal_input_tokens: TimingObservation
    proposal_output_tokens: TimingObservation
    proposal_request_seconds: TimingObservation
    provider_total_duration_seconds: TimingObservation
    stage_seconds: Mapping[str, TimingObservation]
    total_stage_seconds: TimingObservation
    wall_seconds: TimingObservation

    def __post_init__(self) -> None:
        if not self.track or not self.backbone or not self.attempt_id or self.slot_count <= 0:
            raise ValueError("method timing identity and slot_count are required")
        if not isinstance(self.stage_seconds, Mapping):
            raise ValueError("stage_seconds must be a mapping")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "record_type": "method_timing",
            "track": self.track,
            "backbone": self.backbone,
            "attempt_id": self.attempt_id,
            "slot_count": self.slot_count,
            "proposal": {
                "input_tokens": self.proposal_input_tokens.as_dict(),
                "output_tokens": self.proposal_output_tokens.as_dict(),
                "request_seconds": self.proposal_request_seconds.as_dict(),
                "provider_total_duration_seconds": self.provider_total_duration_seconds.as_dict(),
            },
            "verification": {
                "stage_seconds": {
                    name: observation.as_dict()
                    for name, observation in sorted(self.stage_seconds.items())
                },
                "total_stage_seconds": self.total_stage_seconds.as_dict(),
            },
            "wall_seconds": self.wall_seconds.as_dict(),
            "definitions": {
                "proposal_request_seconds": "sum of archived transport elapsed_seconds per provider call; includes retries",
                "provider_total_duration_seconds": "sum of Ollama total_duration nanoseconds converted to seconds",
                "stage_seconds": "sum of StageResult.elapsed_seconds by fixed verification stage; missing stage elapsed remains missing",
                "total_stage_seconds": "sum of stage_seconds observations, not wall-clock elapsed time",
                "wall_seconds": "caller-supplied campaign wall-clock duration; never inferred from component sums",
                "tokens": "sum of provider-reported prompt_tokens/eval_count projections only; T0 has no provider token observation",
            },
        }


def summarize_method_timing(
    method_run: MethodRun,
    outcomes: Iterable[VerificationOutcome] = (),
    *,
    wall_seconds: float | None = None,
) -> MethodTiming:
    """Project method/provider and verification-stage timing without mixing them."""

    rows = tuple(outcomes)
    if rows and len(rows) != len(method_run.slots):
        raise ValueError("verification outcome count must match method slot count")
    responses = tuple(_as_mapping(row) for row in method_run.provider_responses)
    token_input = _response_values(responses, "usage", "prompt_tokens", unit="tokens", source="ollama_provider_usage")
    token_output = _response_values(responses, "usage", "generated_tokens", unit="tokens", source="ollama_provider_usage")
    request_seconds = _response_values(responses, None, "elapsed_seconds", unit="seconds", source="transport_elapsed_seconds")
    provider_seconds = _response_values(
        responses,
        "ollama",
        "total_duration",
        unit="seconds",
        source="ollama_total_duration_nanoseconds",
        scale=1_000_000_000,
    )
    if not responses:
        token_input = _not_applicable("tokens", "no_provider_calls_t0")
        token_output = _not_applicable("tokens", "no_provider_calls_t0")
        request_seconds = _not_applicable("seconds", "no_provider_calls_t0")
        provider_seconds = _not_applicable("seconds", "no_provider_calls_t0")
    stage_names = ("grounding", "symbolic_search", "witness_check", "independent_replay")
    stage_seconds = {
        name: _stage_values(rows, name)
        for name in stage_names
    }
    total_stage = _sum_observations(tuple(stage_seconds.values()), "seconds", "stage_elapsed_seconds")
    wall = _caller_wall(wall_seconds)
    return MethodTiming(
        track=method_run.track.value,
        backbone=method_run.backbone,
        attempt_id=method_run.attempt_id,
        slot_count=len(method_run.slots),
        proposal_input_tokens=token_input,
        proposal_output_tokens=token_output,
        proposal_request_seconds=request_seconds,
        provider_total_duration_seconds=provider_seconds,
        stage_seconds=stage_seconds,
        total_stage_seconds=total_stage,
        wall_seconds=wall,
    )


def _stage_values(rows: tuple[VerificationOutcome, ...], name: str) -> TimingObservation:
    values: list[float | None] = []
    for outcome in rows:
        stage = next((stage for stage in outcome.stages if stage.stage == name), None)
        values.append(stage.elapsed_seconds if stage is not None else None)
    return _aggregate(values, "seconds", "StageResult.elapsed_seconds")


def _response_values(
    responses: tuple[Mapping[str, object], ...],
    parent: str | None,
    field: str,
    *,
    unit: str,
    source: str,
    scale: float = 1.0,
) -> TimingObservation:
    values: list[float | None] = []
    for response in responses:
        container: object = response.get(parent) if parent is not None else response
        value = container.get(field) if isinstance(container, Mapping) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            value = None
        values.append(float(value) / scale if value is not None else None)
    return _aggregate(values, unit, source)


def _aggregate(values: list[float | None] | tuple[TimingObservation, ...], unit: str, source: str) -> TimingObservation:
    if values and isinstance(values[0], TimingObservation):
        observations = values  # type: ignore[assignment]
        total = sum(item.total for item in observations)
        missing = sum(item.missing for item in observations)
        known = total - missing
        value = sum(float(item.value) for item in observations if item.value is not None) if not missing else None
        return TimingObservation(value, known, total, missing, unit, source, "component_missing" if missing else None)
    total = len(values)
    missing = sum(value is None for value in values)
    known = total - missing
    value = sum(float(value) for value in values if value is not None) if not missing else None
    return TimingObservation(value, known, total, missing, unit, source, "field_missing" if missing else None)


def _sum_observations(observations: tuple[TimingObservation, ...], unit: str, source: str) -> TimingObservation:
    total = sum(item.total for item in observations)
    missing = sum(item.missing for item in observations)
    known = total - missing
    value = sum(float(item.value) for item in observations if item.value is not None) if not missing else None
    return TimingObservation(value, known, total, missing, unit, source, "component_missing" if missing else None)


def _not_applicable(unit: str, note: str) -> TimingObservation:
    return TimingObservation(None, 0, 0, 0, unit, "not_applicable", note)


def _caller_wall(value: float | None) -> TimingObservation:
    if value is None:
        return TimingObservation(None, 0, 1, 1, "seconds", "caller_supplied_wall_clock", "wall_time_not_recorded")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)) or value < 0:
        raise ValueError("wall_seconds must be finite and non-negative")
    return TimingObservation(float(value), 1, 1, 0, "seconds", "caller_supplied_wall_clock")


def _as_mapping(value: object) -> Mapping[str, object]:
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    if not isinstance(value, Mapping):
        raise ValueError("provider response must be an object")
    return value


__all__ = ["MethodTiming", "TimingObservation", "summarize_method_timing"]
