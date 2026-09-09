"""Outcome-blind balanced subset selection for baseline/sensitivity studies."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any, Iterable

from ..contracts.canonical import sha256_hex


@dataclass(frozen=True, slots=True)
class SubsetSelection:
    selection_id: str
    seed: int
    target_size: int
    record_ids: tuple[str, ...]
    counts: dict[str, dict[str, int]]
    criteria: dict[str, object]
    selection_hash: str
    population_hash: str = ""
    common_supported_record_ids: tuple[str, ...] = ()
    operational_coverage: dict[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "selection_id": self.selection_id,
            "seed": self.seed,
            "target_size": self.target_size,
            "record_ids": list(self.record_ids),
            "counts": self.counts,
            "criteria": self.criteria,
            "selection_hash": self.selection_hash,
            "population_hash": self.population_hash,
            "common_supported_record_ids": list(self.common_supported_record_ids),
            "operational_coverage": self.operational_coverage,
        }


def select_balanced_subset(
    records: Iterable[dict[str, Any]],
    *,
    target_size: int,
    seed: int,
    min_lineages: int,
    min_families: int,
    record_id_field: str = "instance_id",
    lineage_field: str = "lineage_id",
    family_field: str = "family",
    truth_field: str = "ground_truth",
    positive_label: str = "positive",
    negative_label: str = "negative",
    support_field: str | None = None,
    required_methods: Iterable[str] = (),
    balance_fields: Iterable[str] = (),
) -> SubsetSelection:
    """Select IDs using only pre-outcome strata and a recorded seed.

    The first passes guarantee distinct lineage, family and truth coverage when
    the source population permits it. Remaining slots use deterministic
    least-count greedy ordering so one stratum is not silently overloaded.
    """
    if target_size <= 0 or min_lineages <= 0 or min_families <= 0:
        raise ValueError("target_size and minimum coverage counts must be positive")
    if target_size < max(min_lineages, min_families, 2):
        raise ValueError("target_size cannot satisfy requested coverage")
    if not isinstance(positive_label, str) or not positive_label or not isinstance(negative_label, str) or not negative_label:
        raise ValueError("positive and negative labels must be non-empty strings")
    if positive_label == negative_label:
        raise ValueError("positive and negative labels must differ")
    method_names = tuple(dict.fromkeys(required_methods))
    if any(not isinstance(method, str) or not method for method in method_names):
        raise ValueError("required method names must be non-empty strings")
    if method_names and not support_field:
        raise ValueError("support_field is required when required_methods are requested")
    balance_field_names = tuple(dict.fromkeys(balance_fields))
    if any(not isinstance(field, str) or not field for field in balance_field_names):
        raise ValueError("balance field names must be non-empty strings")
    normalized: list[dict[str, str]] = []
    support_values: dict[str, tuple[str, ...]] = {}
    seen: set[str] = set()
    required = tuple(dict.fromkeys((record_id_field, lineage_field, family_field, truth_field, *balance_field_names)))
    for index, row in enumerate(records, 1):
        if not isinstance(row, dict):
            raise ValueError(f"subset record {index} must be an object")
        values = {field: row.get(field) for field in required}
        if any(not isinstance(value, str) or not value for value in values.values()):
            raise ValueError(f"subset record {index} lacks required identity/strata fields")
        identifier = values[record_id_field]
        if identifier in seen:
            raise ValueError("subset record IDs must be unique")
        seen.add(identifier)
        normalized.append(values)
        if support_field is not None:
            raw_support = row.get(support_field)
            if isinstance(raw_support, dict):
                support = tuple(sorted(name for name, enabled in raw_support.items() if isinstance(name, str) and enabled is True))
            elif isinstance(raw_support, (list, tuple, set, frozenset)):
                support = tuple(sorted(name for name in raw_support if isinstance(name, str)))
            else:
                raise ValueError(f"subset record {index} has invalid {support_field}")
            support_values[identifier] = support
    if target_size > len(normalized):
        raise ValueError("target_size exceeds population")
    if len({row[lineage_field] for row in normalized}) < min_lineages:
        raise ValueError("population cannot satisfy minimum lineage coverage")
    if len({row[family_field] for row in normalized}) < min_families:
        raise ValueError("population cannot satisfy minimum family coverage")
    if not {positive_label, negative_label}.issubset({row[truth_field] for row in normalized}):
        raise ValueError("population must contain positive and negative strata")

    rng = random.Random(seed)
    ranked = sorted(normalized, key=lambda row: (rng.random(), row[record_id_field]))
    rank = {row[record_id_field]: index for index, row in enumerate(ranked)}
    selected: list[dict[str, str]] = []

    def add_first(predicate) -> None:
        for row in ranked:
            if row not in selected and predicate(row):
                selected.append(row)
                return

    for lineage in sorted({row[lineage_field] for row in ranked}):
        if len({row[lineage_field] for row in selected}) >= min_lineages:
            break
        add_first(lambda row, lineage=lineage: row[lineage_field] == lineage)
    for family in sorted({row[family_field] for row in ranked}):
        if len({row[family_field] for row in selected}) >= min_families:
            break
        add_first(lambda row, family=family: row[family_field] == family)
    for truth in (positive_label, negative_label):
        add_first(lambda row, truth=truth: row[truth_field] == truth)

    while len(selected) < target_size:
        remaining = [row for row in ranked if row not in selected]
        if not remaining:
            raise ValueError("subset selection could not fill target size")
        lineage_counts = {key: sum(row[lineage_field] == key for row in selected) for key in {row[lineage_field] for row in ranked}}
        family_counts = {key: sum(row[family_field] == key for row in selected) for key in {row[family_field] for row in ranked}}
        truth_counts = {key: sum(row[truth_field] == key for row in selected) for key in {row[truth_field] for row in ranked}}
        balance_counts = {
            field: {
                key: sum(row[field] == key for row in selected)
                for key in {candidate[field] for candidate in ranked}
            }
            for field in balance_field_names
        }
        row = min(remaining, key=lambda item: (
            *(balance_counts[field][item[field]] for field in balance_field_names),
            lineage_counts[item[lineage_field]],
            family_counts[item[family_field]],
            truth_counts[item[truth_field]],
            rank[item[record_id_field]],
            item[record_id_field],
        ))
        selected.append(row)

    record_ids = tuple(sorted(row[record_id_field] for row in selected))
    counts = {
        "lineage": _counts(selected, lineage_field),
        "family": _counts(selected, family_field),
        "ground_truth": _counts(selected, truth_field),
    }
    for field in balance_field_names:
        counts[field] = _counts(selected, field)
    criteria = {
        "record_id_field": record_id_field,
        "lineage_field": lineage_field,
        "family_field": family_field,
        "truth_field": truth_field,
        "min_lineages": min_lineages,
        "min_families": min_families,
        "positive_label": positive_label,
        "negative_label": negative_label,
        "support_field": support_field,
        "required_methods": list(method_names),
        "balance_fields": list(balance_field_names),
    }
    population_rows = [
        {
            **row,
            **({"supported_methods": support_values[row[record_id_field]]} if support_field is not None else {}),
        }
        for row in normalized
    ]
    population_hash = sha256_hex({"records": sorted(population_rows, key=lambda row: row[record_id_field])})
    operational_coverage = _operational_coverage(
        selected,
        record_id_field=record_id_field,
        support_values=support_values,
        methods=method_names,
    )
    common_supported = tuple(operational_coverage["common_supported_record_ids"])
    payload = {
        "seed": seed,
        "target_size": target_size,
        "record_ids": record_ids,
        "counts": counts,
        "criteria": criteria,
        "population_hash": population_hash,
        "common_supported_record_ids": common_supported,
        "operational_coverage": operational_coverage,
    }
    selection_hash = sha256_hex(payload)
    return SubsetSelection(
        f"subset-{selection_hash[:16]}", seed, target_size, record_ids, counts, criteria,
        selection_hash, population_hash, common_supported, operational_coverage,
    )


def _counts(rows: list[dict[str, str]], field: str) -> dict[str, int]:
    return {key: sum(row[field] == key for row in rows) for key in sorted({row[field] for row in rows})}


def _operational_coverage(
    rows: list[dict[str, str]],
    *,
    record_id_field: str,
    support_values: dict[str, tuple[str, ...]],
    methods: tuple[str, ...],
) -> dict[str, object]:
    identifiers = [row[record_id_field] for row in rows]
    eligible = {
        method: {identifier for identifier in identifiers if method in support_values.get(identifier, ())}
        for method in methods
    }
    common = set.intersection(*eligible.values()) if eligible else set()
    return {
        "denominator": len(identifiers),
        "methods": {
            method: {
                "eligible": len(ids),
                "unsupported": len(identifiers) - len(ids),
                "fraction": len(ids) / len(identifiers) if identifiers else None,
            }
            for method, ids in eligible.items()
        },
        "common_supported_record_ids": sorted(common),
        "common_supported_count": len(common),
        "outcomes_used": False,
    }


__all__ = ["SubsetSelection", "select_balanced_subset"]
