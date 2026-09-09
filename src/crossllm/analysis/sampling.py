"""Deterministic stratified probability sampling for M09.03."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any, Callable, Iterable


@dataclass(frozen=True, slots=True)
class SampledRecord:
    record_id: str
    stratum: str
    inclusion_probability: float
    weight: float

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "stratum": self.stratum,
            "inclusion_probability": self.inclusion_probability,
            "weight": self.weight,
        }


def stratified_sample(
    records: Iterable[dict[str, Any]],
    *,
    record_id: Callable[[dict[str, Any]], str],
    stratum: Callable[[dict[str, Any]], str],
    sample_size_by_stratum: dict[str, int],
    seed: int,
) -> tuple[SampledRecord, ...]:
    """Sample without replacement and return design weights ``N_h/n_h``."""
    groups: dict[str, list[dict[str, Any]]] = {}
    seen_ids: set[str] = set()
    for record in records:
        key = stratum(record)
        identifier = record_id(record)
        if not identifier:
            raise ValueError("sample records require non-empty IDs")
        if identifier in seen_ids:
            raise ValueError("sample record IDs must be unique")
        seen_ids.add(identifier)
        groups.setdefault(key, []).append(record)
    rng = random.Random(seed)
    result: list[SampledRecord] = []
    for key in sorted(groups):
        population = sorted(groups[key], key=record_id)
        requested = sample_size_by_stratum.get(key, 0)
        if requested < 0:
            raise ValueError("sample sizes must be non-negative")
        if requested > len(population):
            raise ValueError(f"sample size exceeds population in stratum {key}")
        if requested == 0:
            continue
        selected = sorted(rng.sample(population, requested), key=record_id)
        probability = requested / len(population)
        result.extend(SampledRecord(record_id(item), key, probability, 1 / probability) for item in selected)
    return tuple(result)
