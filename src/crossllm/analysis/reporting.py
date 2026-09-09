"""Inference/report helpers that keep primary and secondary families separate."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import mean
from typing import Mapping

from .inference import (
    BootstrapSummary,
    SignTestResult,
    exact_two_sided_sign_test,
    holm_adjust,
    paired_lineage_bootstrap,
)


@dataclass(frozen=True, slots=True)
class ContrastInference:
    contrast: str
    sign_test: SignTestResult
    bootstrap: BootstrapSummary
    adjusted_p_value: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "contrast": self.contrast,
            "sign_test": self.sign_test.as_dict(),
            "bootstrap": self.bootstrap.as_dict(),
            "adjusted_p_value": self.adjusted_p_value,
        }


def analyze_contrast_family(
    contrasts: Mapping[str, Mapping[str, float]],
    *,
    draws: int = 10_000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[ContrastInference, ...]:
    """Run paired lineage inference, applying Holm only within this family."""
    if not 0 < alpha <= 1:
        raise ValueError("alpha must be in (0, 1]")
    normalized: dict[str, dict[str, float]] = {}
    for name, values in contrasts.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("contrast names must be non-empty strings")
        if not isinstance(values, Mapping) or any(
            not isinstance(lineage, str) or not lineage.strip()
            or not isinstance(effect, (int, float))
            or isinstance(effect, bool)
            or not isfinite(float(effect))
            for lineage, effect in values.items()
        ):
            raise ValueError("contrast effects must be finite numeric lineage mappings")
        normalized[name] = {lineage: float(effect) for lineage, effect in values.items()}
    signs = {name: exact_two_sided_sign_test(values.values()) for name, values in sorted(normalized.items())}
    raw_p = {name: result.p_value for name, result in signs.items() if result.p_value is not None}
    adjusted = holm_adjust(raw_p)
    result: list[ContrastInference] = []
    for index, (name, values) in enumerate(sorted(normalized.items())):
        result.append(ContrastInference(
            name,
            signs[name],
            paired_lineage_bootstrap(values, draws=draws, seed=seed + index),
            adjusted.get(name),
        ))
    return tuple(result)


def zero_event_upper_bound(independent_units: int, *, confidence: float = 0.95) -> float:
    """One-sided event-probability bound when zero events were observed."""
    if independent_units <= 0:
        raise ValueError("independent_units must be positive")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between zero and one")
    return 1 - (1 - confidence) ** (1 / independent_units)


def leave_one_lineage_out(values: dict[str, float]) -> dict[str, float | None]:
    """Sensitivity means after removing each complete lineage."""
    if not values:
        return {}
    result: dict[str, float | None] = {}
    for lineage in sorted(values):
        remaining = [value for key, value in values.items() if key != lineage]
        result[lineage] = mean(remaining) if remaining else None
    return result
