"""Specification-conditioned backend contracts (M07.03)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .external import BaselineResult, ExternalToolAdapter, ToolSpec


@dataclass(frozen=True, slots=True)
class EffortVector:
    """Measured effort with source-track and storage-track counters separated."""

    wall_seconds: float
    cpu_seconds: float | None = None
    peak_memory_mib: int | None = None
    track_steps: int = 0
    storage_steps: int = 0
    solver_queries: int = 0

    def __post_init__(self) -> None:
        if self.wall_seconds < 0:
            raise ValueError("wall_seconds must be non-negative")
        for name in ("cpu_seconds",):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")
        for name in ("peak_memory_mib", "track_steps", "storage_steps", "solver_queries"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")

    def as_dict(self) -> dict[str, int | float | None]:
        return {
            "wall_seconds": self.wall_seconds,
            "cpu_seconds": self.cpu_seconds,
            "peak_memory_mib": self.peak_memory_mib,
            "track_steps": self.track_steps,
            "storage_steps": self.storage_steps,
            "solver_queries": self.solver_queries,
        }


@dataclass(frozen=True, slots=True)
class ConditionedSpec:
    method_id: str
    track: str
    tool: ToolSpec
    independent_property_hash: str
    semantic_harness_hash: str
    track_model_hash: str
    storage_model_hash: str
    common_harness_id: str

    def __post_init__(self) -> None:
        values = (
            self.method_id, self.track, self.independent_property_hash,
            self.semantic_harness_hash, self.track_model_hash, self.storage_model_hash,
            self.common_harness_id,
        )
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError("conditioned spec identity and semantic hashes are required")
        for name in ("independent_property_hash", "semantic_harness_hash", "track_model_hash", "storage_model_hash"):
            value = getattr(self, name)
            if len(value) != 64 or value != value.lower() or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "method_id": self.method_id,
            "track": self.track,
            "tool": self.tool.as_dict(),
            "independent_property_hash": self.independent_property_hash,
            "semantic_harness_hash": self.semantic_harness_hash,
            "track_model_hash": self.track_model_hash,
            "storage_model_hash": self.storage_model_hash,
            "common_harness_id": self.common_harness_id,
        }


@dataclass(frozen=True, slots=True)
class ConditionedResult:
    spec: ConditionedSpec
    result: BaselineResult
    effort: EffortVector | None
    effort_missing_reason: str | None = None

    def __post_init__(self) -> None:
        if self.effort is None and not self.effort_missing_reason:
            raise ValueError("conditioned result must explain missing effort")
        if self.effort is not None and self.effort_missing_reason is not None:
            raise ValueError("conditioned result cannot carry effort and missing reason")

    def as_dict(self) -> dict[str, object]:
        return {
            "spec": self.spec.as_dict(),
            "result": self.result.as_dict(),
            "effort": self.effort.as_dict() if self.effort is not None else None,
            "effort_missing_reason": self.effort_missing_reason,
            "track_storage_separated": True,
        }


class ConditionedAdapter:
    def __init__(self, external: ExternalToolAdapter | None = None) -> None:
        self.external = external or ExternalToolAdapter()

    def run(
        self,
        spec: ConditionedSpec,
        workdir: Path,
        *,
        effort: EffortVector | None = None,
        effort_missing_reason: str | None = None,
    ) -> ConditionedResult:
        result = self.external.run(spec.tool, workdir)
        return ConditionedResult(spec, result, effort, effort_missing_reason)


__all__ = ["ConditionedAdapter", "ConditionedResult", "ConditionedSpec", "EffortVector"]
