"""Paired lineage bootstrap and exact sign-test utilities for M09.05/M09.08."""

from __future__ import annotations

from dataclasses import dataclass
from math import comb
import random
from statistics import mean
from typing import Iterable


@dataclass(frozen=True, slots=True)
class SignTestResult:
    wins: int
    losses: int
    ties: int
    effective_n: int
    p_value: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "effective_n": self.effective_n,
            "p_value": self.p_value,
        }


@dataclass(frozen=True, slots=True)
class BootstrapSummary:
    estimate: float | None
    ci_low: float | None
    ci_high: float | None
    draws: int
    seed: int
    lineage_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "estimate": self.estimate,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "draws": self.draws,
            "seed": self.seed,
            "lineage_count": self.lineage_count,
        }


def exact_two_sided_sign_test(effects: Iterable[float]) -> SignTestResult:
    values = list(effects)
    wins = sum(value > 0 for value in values)
    losses = sum(value < 0 for value in values)
    ties = len(values) - wins - losses
    effective_n = wins + losses
    if effective_n == 0:
        return SignTestResult(wins, losses, ties, 0, None)
    observed = min(wins, losses)
    probability = sum(comb(effective_n, k) for k in range(effective_n + 1) if min(k, effective_n - k) <= observed)
    return SignTestResult(wins, losses, ties, effective_n, probability / (2**effective_n))


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    """Holm step-down adjusted p-values, retaining original keys."""
    if any(value < 0 or value > 1 for value in p_values.values()):
        raise ValueError("p-values must be in [0, 1]")
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for index, (key, value) in enumerate(ordered):
        running = max(running, min(1.0, (total - index) * value))
        adjusted[key] = running
    return adjusted


def paired_lineage_bootstrap(
    lineage_effects: dict[str, float],
    *,
    draws: int = 10_000,
    seed: int = 0,
    confidence: float = 0.95,
) -> BootstrapSummary:
    """Resample complete lineage effects, preserving pairing within each effect."""
    if draws <= 0:
        raise ValueError("draws must be positive")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between zero and one")
    values = [lineage_effects[key] for key in sorted(lineage_effects)]
    if not values:
        return BootstrapSummary(None, None, None, draws, seed, 0)
    rng = random.Random(seed)
    samples = [mean(rng.choices(values, k=len(values))) for _ in range(draws)]
    samples.sort()
    alpha = (1 - confidence) / 2
    return BootstrapSummary(
        estimate=mean(values),
        ci_low=_quantile(samples, alpha),
        ci_high=_quantile(samples, 1 - alpha),
        draws=draws,
        seed=seed,
        lineage_count=len(values),
    )


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("quantile requires values")
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction
