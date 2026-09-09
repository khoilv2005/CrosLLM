"""Phase-separated resource telemetry for M08.05."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .resources import ResourceUsage


class EffortPhase(StrEnum):
    METHOD_HORIZON = "method_horizon"
    PREPROCESSING = "preprocessing"
    ADJUDICATION = "adjudication"
    CALIBRATION = "calibration"


@dataclass(frozen=True, slots=True)
class TelemetryRecord:
    """One measured resource vector with explicit effort attribution."""

    phase: EffortPhase
    usage: ResourceUsage
    campaign_id: str | None = None
    attempt_id: str | None = None
    worker_id: str | None = None
    queue_seconds: float = 0.0
    throttled_seconds: float = 0.0
    throttle_count: int = 0

    def __post_init__(self) -> None:
        if self.queue_seconds < 0 or self.throttled_seconds < 0:
            raise ValueError("queue and throttled seconds must be non-negative")
        if self.throttle_count < 0:
            raise ValueError("throttle_count must be non-negative")

    def as_dict(self) -> dict[str, Any]:
        payload = self.usage.as_resource_vector()
        payload.update({
            "phase": self.phase.value,
            "campaign_id": self.campaign_id,
            "attempt_id": self.attempt_id,
            "worker_id": self.worker_id,
            "queue_seconds": self.queue_seconds,
            "throttled_seconds": self.throttled_seconds,
            "throttle_count": self.throttle_count,
            "cost_usd": self.usage.cost_usd,
        })
        return payload


class TelemetryLedger:
    """Append-only in-memory collection with phase-separated aggregation."""

    def __init__(self) -> None:
        self._records: list[TelemetryRecord] = []

    @property
    def records(self) -> tuple[TelemetryRecord, ...]:
        return tuple(self._records)

    def append(self, record: TelemetryRecord) -> None:
        self._records.append(record)

    def aggregate(self, phase: EffortPhase) -> dict[str, Any]:
        selected = [record for record in self._records if record.phase == phase]
        total = ResourceUsage(
            cpu_core_seconds=sum(record.usage.cpu_core_seconds for record in selected),
            solver_seconds=sum(record.usage.solver_seconds for record in selected),
            memory_high_water_bytes=(
                max((record.usage.memory_high_water_bytes for record in selected if record.usage.memory_high_water_bytes is not None), default=None)
            ),
            wall_seconds=sum(record.usage.wall_seconds for record in selected),
            input_tokens=self._sum_optional(record.usage.input_tokens for record in selected),
            generated_tokens=self._sum_optional(record.usage.generated_tokens for record in selected),
            cost_usd=self._sum_optional_float(record.usage.cost_usd for record in selected),
            missing_field_reasons=self._merge_missing_reasons(selected),
        )
        payload = total.as_resource_vector()
        payload.update({
            "phase": phase.value,
            "record_count": len(selected),
            "queue_seconds": sum(record.queue_seconds for record in selected),
            "throttled_seconds": sum(record.throttled_seconds for record in selected),
            "throttle_count": sum(record.throttle_count for record in selected),
            "cost_usd": total.cost_usd,
        })
        return payload

    @staticmethod
    def _sum_optional(values: Any) -> int | None:
        materialized = list(values)
        if not materialized or any(value is None for value in materialized):
            return None
        return sum(materialized)

    @staticmethod
    def _sum_optional_float(values: Any) -> float | None:
        materialized = list(values)
        if not materialized or any(value is None for value in materialized):
            return None
        return sum(materialized)

    @staticmethod
    def _merge_missing_reasons(records: list[TelemetryRecord]) -> dict[str, str]:
        reasons: dict[str, str] = {}
        for record in records:
            reasons.update(record.usage.missing_field_reasons)
        return reasons
