"""Agreement and confusion summaries for blinded labels (M09.09)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import isfinite
import random
from statistics import mean
from typing import Iterable


@dataclass(frozen=True, slots=True)
class AgreementSummary:
    matched: int
    missing_left: int
    missing_right: int
    observed_agreement: float | None
    kappa: float | None
    confusion: dict[str, dict[str, int]]
    observed_agreement_ci: tuple[float, float] | None = None
    kappa_ci: tuple[float, float] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "matched": self.matched,
            "missing_left": self.missing_left,
            "missing_right": self.missing_right,
            "observed_agreement": self.observed_agreement,
            "kappa": self.kappa,
            "confusion": self.confusion,
            "observed_agreement_ci": self.observed_agreement_ci,
            "kappa_ci": self.kappa_ci,
        }


def agreement_summary(
    left: dict[str, str],
    right: dict[str, str],
    *,
    clusters: dict[str, str] | None = None,
    draws: int = 10_000,
    seed: int = 0,
    confidence: float = 0.95,
) -> AgreementSummary:
    """Summarize labels and optionally bootstrap complete clusters.

    ``clusters`` maps a matched finding ID to its independent unit (normally a
    lineage). When supplied, uncertainty resamples clusters with replacement
    and carries every finding in each selected cluster together. This avoids
    presenting correlated findings as independent annotator observations.
    """
    if draws <= 1:
        raise ValueError("draws must be greater than one")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between zero and one")
    keys = sorted(set(left) & set(right))
    missing_left = len(set(right) - set(left))
    missing_right = len(set(left) - set(right))
    if not keys:
        return AgreementSummary(0, missing_left, missing_right, None, None, {})
    matrix: Counter[tuple[str, str]] = Counter((left[key], right[key]) for key in keys)
    labels = sorted({label for pair in matrix for label in pair})
    confusion = {row: {column: matrix[(row, column)] for column in labels} for row in labels}
    observed, kappa = _agreement_statistics([(left[key], right[key]) for key in keys])
    observed_ci: tuple[float, float] | None = None
    kappa_ci: tuple[float, float] | None = None
    if clusters is not None:
        unknown = set(clusters) - set(keys)
        missing_clusters = set(keys) - set(clusters)
        if unknown or missing_clusters:
            raise ValueError("clusters must cover exactly the matched label IDs")
        cluster_groups: dict[str, list[str]] = {}
        for key in keys:
            cluster = clusters[key]
            if not isinstance(cluster, str) or not cluster:
                raise ValueError("cluster IDs must be non-empty strings")
            cluster_groups.setdefault(cluster, []).append(key)
        rng = random.Random(seed)
        cluster_ids = sorted(cluster_groups)
        observed_draws: list[float] = []
        kappa_draws: list[float] = []
        for _ in range(draws):
            sampled = rng.choices(cluster_ids, k=len(cluster_ids))
            pairs = [
                (left[key], right[key])
                for cluster in sampled
                for key in cluster_groups[cluster]
            ]
            sampled_observed, sampled_kappa = _agreement_statistics(pairs)
            if sampled_observed is not None:
                observed_draws.append(sampled_observed)
            if sampled_kappa is not None:
                kappa_draws.append(sampled_kappa)
        observed_ci = _bootstrap_interval(observed_draws, confidence)
        kappa_ci = _bootstrap_interval(kappa_draws, confidence)
    return AgreementSummary(
        len(keys),
        missing_left,
        missing_right,
        observed,
        kappa,
        confusion,
        observed_ci,
        kappa_ci,
    )


def _agreement_statistics(pairs: list[tuple[str, str]]) -> tuple[float | None, float | None]:
    if not pairs:
        return None, None
    matrix: Counter[tuple[str, str]] = Counter(pairs)
    labels = sorted({label for pair in matrix for label in pair})
    total = len(pairs)
    observed = sum(matrix[(label, label)] for label in labels) / total
    left_counts = Counter(left for left, _right in pairs)
    right_counts = Counter(right for _left, right in pairs)
    expected = sum(left_counts[label] * right_counts[label] for label in labels) / (total ** 2)
    kappa = 1.0 if expected == 1.0 and observed == 1.0 else (
        0.0 if expected == 1.0 else (observed - expected) / (1 - expected)
    )
    return observed, kappa


def _bootstrap_interval(values: list[float], confidence: float) -> tuple[float, float] | None:
    if not values:
        return None
    values.sort()
    alpha = (1 - confidence) / 2
    return _quantile(values, alpha), _quantile(values, 1 - alpha)


def _quantile(values: list[float], probability: float) -> float:
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    value = values[lower] + (values[upper] - values[lower]) * fraction
    return value if isfinite(value) else mean(values)
