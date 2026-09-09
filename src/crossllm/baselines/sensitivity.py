"""Prespecified M07.07 sensitivity-cell contracts.

The builder enumerates the scientific matrix only. It does not execute tools or
infer eligibility from a successful outcome. Each cell carries an explicit
method/track, budget and either a measured denominator, a pending eligibility
state, or an unsupported reason.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..contracts.canonical import sha256_hex


class EligibilityStatus(StrEnum):
    PENDING = "pending"
    ELIGIBLE = "eligible"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class CellEligibility:
    status: EligibilityStatus
    denominator: int | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status is EligibilityStatus.ELIGIBLE:
            if self.denominator is None or self.denominator < 0 or self.reason is not None:
                raise ValueError("eligible cell requires a non-negative denominator and no reason")
        elif self.status is EligibilityStatus.UNSUPPORTED:
            if not self.reason or self.denominator not in (None, 0):
                raise ValueError("unsupported cell requires a reason and no positive denominator")
        elif self.denominator is not None or self.reason is not None:
            raise ValueError("pending cell cannot carry denominator or reason")

    @classmethod
    def pending(cls) -> "CellEligibility":
        return cls(EligibilityStatus.PENDING)

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "eligible_denominator": self.denominator,
            "unsupported_reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class CellBudget:
    solver_timeout_seconds: int
    horizon_minutes: int
    worker_cpu_cores: int = 4
    worker_memory_gib: int = 16
    campaign_wall_seconds: int = 3600

    def __post_init__(self) -> None:
        if self.solver_timeout_seconds <= 0 or self.horizon_minutes <= 0:
            raise ValueError("solver timeout and horizon must be positive")
        if self.worker_cpu_cores <= 0 or self.worker_memory_gib <= 0 or self.campaign_wall_seconds <= 0:
            raise ValueError("resource budget values must be positive")

    def as_dict(self) -> dict[str, int]:
        return {
            "solver_timeout_seconds": self.solver_timeout_seconds,
            "horizon_minutes": self.horizon_minutes,
            "worker_cpu_cores": self.worker_cpu_cores,
            "worker_memory_gib": self.worker_memory_gib,
            "campaign_wall_seconds": self.campaign_wall_seconds,
        }


@dataclass(frozen=True, slots=True)
class SensitivityCell:
    method: str
    track: str
    proposal_prefix: int
    k_tx: int
    k_ch: int
    buffer_bound: int
    solver_timeout_seconds: int
    horizon_minutes: int
    channel_mode: str
    reorg_mode: str
    challenge_timing: str
    attestation_profile: str
    program_size_stratum: str
    budget: CellBudget
    eligibility: CellEligibility = CellEligibility.pending()

    def __post_init__(self) -> None:
        values = (
            self.method, self.track, self.channel_mode, self.reorg_mode,
            self.challenge_timing, self.attestation_profile, self.program_size_stratum,
        )
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError("sensitivity cell identity/config values are required")
        if self.proposal_prefix <= 0 or self.k_tx <= 0 or self.k_ch <= 0 or self.buffer_bound <= 0:
            raise ValueError("sensitivity bounds must be positive")
        if self.solver_timeout_seconds != self.budget.solver_timeout_seconds or self.horizon_minutes != self.budget.horizon_minutes:
            raise ValueError("cell dimensions must match its budget")

    def _payload(self) -> dict[str, object]:
        return {
            "method": self.method,
            "track": self.track,
            "proposal_prefix": self.proposal_prefix,
            "k_tx": self.k_tx,
            "k_ch": self.k_ch,
            "buffer_bound": self.buffer_bound,
            "solver_timeout_seconds": self.solver_timeout_seconds,
            "horizon_minutes": self.horizon_minutes,
            "channel_mode": self.channel_mode,
            "reorg_mode": self.reorg_mode,
            "challenge_timing": self.challenge_timing,
            "attestation_profile": self.attestation_profile,
            "program_size_stratum": self.program_size_stratum,
            "budget": self.budget.as_dict(),
            "eligibility": self.eligibility.as_dict(),
        }

    @property
    def cell_id(self) -> str:
        return f"cell-{sha256_hex(self._payload())[:20]}"

    def as_dict(self) -> dict[str, object]:
        return {"cell_id": self.cell_id, **self._payload()}


@dataclass(frozen=True, slots=True)
class SensitivityMatrix:
    matrix_id: str
    cells: tuple[SensitivityCell, ...]

    def __post_init__(self) -> None:
        if not self.matrix_id:
            raise ValueError("sensitivity matrix identity is required")
        ids = [cell.cell_id for cell in self.cells]
        if len(ids) != len(set(ids)):
            raise ValueError("sensitivity cell IDs must be unique")

    @property
    def matrix_hash(self) -> str:
        return sha256_hex({"schema_version": 1, "matrix_id": self.matrix_id, "cells": [cell.as_dict() for cell in self.cells]})

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "matrix_id": self.matrix_id,
            "matrix_hash": self.matrix_hash,
            "cell_count": len(self.cells),
            "cells": [cell.as_dict() for cell in self.cells],
        }


EligibilityResolver = Callable[..., CellEligibility]


def build_sensitivity_matrix(
    *,
    methods: Iterable[str],
    tracks: Iterable[str],
    attestation_profiles: Iterable[str],
    program_size_strata: Iterable[str],
    eligibility: EligibilityResolver | None = None,
    matrix_id: str = "m07-sensitivity-v1",
    proposal_prefixes: tuple[int, ...] = (1, 2, 4, 8),
    transaction_bounds: tuple[int, ...] = (2, 4, 6, 8),
    channel_bounds: tuple[tuple[int, int], ...] = ((6, 1), (12, 2), (24, 4)),
    solver_timeouts: tuple[int, ...] = (10, 30, 120),
    horizons_minutes: tuple[int, ...] = (15, 60),
    channel_modes: tuple[str, ...] = ("fifo", "reordering"),
    reorg_modes: tuple[str, ...] = ("none", "bounded_pre_finality"),
    challenge_timings: tuple[str, ...] = ("before", "at", "after"),
) -> SensitivityMatrix:
    """Enumerate the prespecified Cartesian product in stable order."""
    method_names = _names(methods, "methods")
    track_names = _names(tracks, "tracks")
    attestations = _names(attestation_profiles, "attestation_profiles")
    sizes = _names(program_size_strata, "program_size_strata")
    dimensions = (
        proposal_prefixes, transaction_bounds, channel_bounds, solver_timeouts,
        horizons_minutes, channel_modes, reorg_modes, challenge_timings,
    )
    if any(not values for values in dimensions):
        raise ValueError("every sensitivity dimension must contain at least one value")
    cells: list[SensitivityCell] = []
    for method in method_names:
        for track in track_names:
            for proposal_prefix in proposal_prefixes:
                for k_tx in transaction_bounds:
                    for k_ch, buffer_bound in channel_bounds:
                        for solver_timeout in solver_timeouts:
                            for horizon in horizons_minutes:
                                for channel_mode in channel_modes:
                                    for reorg_mode in reorg_modes:
                                        for challenge_timing in challenge_timings:
                                            for attestation in attestations:
                                                for size in sizes:
                                                    budget = CellBudget(solver_timeout, horizon)
                                                    cell_args = {
                                                        "method": method,
                                                        "track": track,
                                                        "proposal_prefix": proposal_prefix,
                                                        "k_tx": k_tx,
                                                        "k_ch": k_ch,
                                                        "buffer_bound": buffer_bound,
                                                        "solver_timeout_seconds": solver_timeout,
                                                        "horizon_minutes": horizon,
                                                        "channel_mode": channel_mode,
                                                        "reorg_mode": reorg_mode,
                                                        "challenge_timing": challenge_timing,
                                                        "attestation_profile": attestation,
                                                        "program_size_stratum": size,
                                                        "budget": budget,
                                                    }
                                                    status = eligibility(**cell_args) if eligibility is not None else CellEligibility.pending()
                                                    if not isinstance(status, CellEligibility):
                                                        raise ValueError("eligibility resolver must return CellEligibility")
                                                    cells.append(SensitivityCell(**cell_args, eligibility=status))
    return SensitivityMatrix(matrix_id, tuple(cells))


def _names(values: Iterable[str], field: str) -> tuple[str, ...]:
    names = tuple(dict.fromkeys(values))
    if not names or any(not isinstance(name, str) or not name for name in names):
        raise ValueError(f"{field} must contain non-empty names")
    return names


__all__ = [
    "CellBudget", "CellEligibility", "EligibilityStatus", "SensitivityCell",
    "SensitivityMatrix", "build_sensitivity_matrix",
]
