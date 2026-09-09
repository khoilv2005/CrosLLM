"""Strict JSON codecs for calibration and development-freeze artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .planning import (
    BudgetInputs,
    CalibrationObservation,
    CalibrationSetting,
    SelectionDecision,
    SelectionRule,
    select_development_setting,
)


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read calibration JSON: {error}") from error


def load_settings(path: Path) -> tuple[CalibrationSetting, ...]:
    raw = read_json(path)
    rows = raw.get("settings") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("settings input must be a JSON list or object with settings")
    return tuple(_setting(row, index) for index, row in enumerate(rows, 1))


def load_observations(path: Path) -> tuple[CalibrationObservation, ...]:
    raw = read_json(path)
    rows = raw.get("observations") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("observations input must be a JSON list or object with observations")
    return tuple(_observation(row, index) for index, row in enumerate(rows, 1))


def load_selection_decision(path: Path) -> SelectionDecision:
    raw = read_json(path)
    if not isinstance(raw, dict):
        raise ValueError("selection decision must be a JSON object")
    selected_raw = raw.get("selected_setting")
    eligible_raw = raw.get("eligible_settings")
    observations_raw = raw.get("observations")
    if not isinstance(selected_raw, dict) or not isinstance(eligible_raw, list) or not isinstance(observations_raw, list):
        raise ValueError("selection decision lacks provenance settings/observations")
    settings = [_setting(selected_raw, 1)] + [_setting(row, index + 1) for index, row in enumerate(eligible_raw)]
    unique_settings = {setting.setting_id: setting for setting in settings}
    observations = tuple(_observation(row, index) for index, row in enumerate(observations_raw, 1))
    rule = SelectionRule(
        recall_tolerance=_number(raw, "recall_tolerance"),
        max_truncation_rate=_number(raw, "max_truncation_rate"),
        development_only=raw.get("development_only") is True,
    )
    recomputed = select_development_setting(list(unique_settings.values()), list(observations), rule=rule)
    if raw.get("selection_hash") != recomputed.selection_hash:
        raise ValueError("selection decision hash mismatch")
    return recomputed


def load_budget_inputs(path: Path) -> BudgetInputs:
    raw = read_json(path)
    if not isinstance(raw, dict):
        raise ValueError("budget input must be a JSON object")
    allowed = {field for field in BudgetInputs.__dataclass_fields__}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"unknown budget fields: {', '.join(unknown)}")
    try:
        return BudgetInputs(**raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid budget inputs: {error}") from error


def load_hashes(path: Path) -> dict[str, str]:
    raw = read_json(path)
    hashes = raw.get("hashes") if isinstance(raw, dict) and isinstance(raw.get("hashes"), dict) else raw
    if not isinstance(hashes, dict) or any(not isinstance(key, str) or not isinstance(value, str) or not value for key, value in hashes.items()):
        raise ValueError("hashes input must be an object of non-empty strings")
    return dict(hashes)


def _setting(row: object, index: int) -> CalibrationSetting:
    if not isinstance(row, dict):
        raise ValueError(f"setting {index} must be an object")
    try:
        return CalibrationSetting(
            row["setting_id"], row["reasoning_level"], row["temperature"],
            row["output_cap"], row["estimated_cost_usd"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid setting {index}: {error}") from error


def _observation(row: object, index: int) -> CalibrationObservation:
    if not isinstance(row, dict):
        raise ValueError(f"observation {index} must be an object")
    try:
        return CalibrationObservation(
            row["setting_id"], row["split"], row.get("recall"),
            row.get("truncation_rate"), row["calls"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid observation {index}: {error}") from error


def _number(row: dict[str, Any], field: str) -> float:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    return float(value)


__all__ = [
    "load_budget_inputs",
    "load_hashes",
    "load_observations",
    "load_selection_decision",
    "load_settings",
    "read_json",
]
