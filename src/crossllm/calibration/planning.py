"""Development selection and budget arithmetic for M10.01/M10.06/M10.07."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from ..contracts.canonical import sha256_hex


@dataclass(frozen=True, slots=True)
class CalibrationSetting:
    setting_id: str
    reasoning_level: str
    temperature: float
    output_cap: int
    estimated_cost_usd: float

    def __post_init__(self) -> None:
        if not self.setting_id or not self.reasoning_level:
            raise ValueError("calibration setting identity is required")
        if self.temperature < 0 or self.output_cap <= 0 or self.estimated_cost_usd < 0:
            raise ValueError("calibration setting values must be non-negative")

    def as_dict(self) -> dict[str, object]:
        return {
            "setting_id": self.setting_id,
            "reasoning_level": self.reasoning_level,
            "temperature": self.temperature,
            "output_cap": self.output_cap,
            "estimated_cost_usd": self.estimated_cost_usd,
        }


def build_compact_calibration_menu(
    *,
    reasoning_levels: tuple[str, str],
    starting_temperature: float,
    temperature_delta: float,
    output_cap: int,
    estimated_cost_usd: Mapping[tuple[str, float], float] | None = None,
) -> tuple[CalibrationSetting, ...]:
    """Build the prespecified 2-by-2 development-only calibration menu.

    The function only constructs candidate settings. It never consumes an
    outcome and therefore cannot adapt the menu to development performance.
    """
    if len(reasoning_levels) != 2 or len(set(reasoning_levels)) != 2 or any(not level for level in reasoning_levels):
        raise ValueError("calibration menu requires exactly two distinct reasoning levels")
    if starting_temperature < 0 or temperature_delta <= 0:
        raise ValueError("starting temperature must be non-negative and delta must be positive")
    if starting_temperature - temperature_delta < 0:
        raise ValueError("lower calibration temperature cannot be negative")
    if output_cap <= 0:
        raise ValueError("output_cap must be positive")
    # Decimal-looking temperatures must produce stable IDs and cost-key
    # lookups even though the public API accepts ordinary Python floats.
    temperatures = (
        round(starting_temperature - temperature_delta, 12),
        round(starting_temperature + temperature_delta, 12),
    )
    costs = estimated_cost_usd or {}
    settings: list[CalibrationSetting] = []
    for level in reasoning_levels:
        for temperature in temperatures:
            cost = costs.get((level, temperature), 0.0)
            if cost < 0:
                raise ValueError("estimated calibration costs must be non-negative")
            setting_id = f"cal-{level}-t{temperature:g}"
            settings.append(CalibrationSetting(setting_id, level, temperature, output_cap, cost))
    return tuple(settings)


@dataclass(frozen=True, slots=True)
class CalibrationObservation:
    setting_id: str
    split: str
    recall: float | None
    truncation_rate: float | None
    calls: int

    def __post_init__(self) -> None:
        if self.split not in {"development", "evaluation"}:
            raise ValueError("split must be development or evaluation")
        if self.recall is not None and not 0 <= self.recall <= 1:
            raise ValueError("recall must be in [0,1]")
        if self.truncation_rate is not None and not 0 <= self.truncation_rate <= 1:
            raise ValueError("truncation_rate must be in [0,1]")
        if self.calls <= 0:
            raise ValueError("calls must be positive")


@dataclass(frozen=True, slots=True)
class SelectionRule:
    recall_tolerance: float = 0.02
    max_truncation_rate: float = 0.05
    development_only: bool = True

    def __post_init__(self) -> None:
        if self.recall_tolerance < 0 or self.max_truncation_rate < 0:
            raise ValueError("selection tolerances must be non-negative")
        if not self.development_only:
            raise ValueError("calibration selection must be development-only")


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    setting_id: str
    eligible_setting_ids: tuple[str, ...]
    best_development_recall: float
    rule: SelectionRule
    selection_hash: str
    selected_setting: CalibrationSetting | None = None
    eligible_settings: tuple[CalibrationSetting, ...] = ()
    observations: tuple[CalibrationObservation, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "setting_id": self.setting_id,
            "eligible_setting_ids": list(self.eligible_setting_ids),
            "best_development_recall": self.best_development_recall,
            "recall_tolerance": self.rule.recall_tolerance,
            "max_truncation_rate": self.rule.max_truncation_rate,
            "development_only": self.rule.development_only,
            "selection_hash": self.selection_hash,
            "selected_setting": self.selected_setting.as_dict() if self.selected_setting else None,
            "eligible_settings": [setting.as_dict() for setting in self.eligible_settings],
            "observations": [
                {
                    "setting_id": observation.setting_id,
                    "split": observation.split,
                    "recall": observation.recall,
                    "truncation_rate": observation.truncation_rate,
                    "calls": observation.calls,
                }
                for observation in self.observations
            ],
        }


def select_development_setting(
    settings: list[CalibrationSetting],
    observations: list[CalibrationObservation],
    *,
    rule: SelectionRule | None = None,
) -> SelectionDecision:
    rule = rule or SelectionRule()
    if not settings or not observations:
        raise ValueError("settings and observations are required")
    if len({setting.setting_id for setting in settings}) != len(settings):
        raise ValueError("setting IDs must be unique")
    if any(observation.split != "development" for observation in observations):
        raise ValueError("evaluation observations cannot enter development selection")
    if len({observation.setting_id for observation in observations}) != len(observations):
        raise ValueError("one development observation per setting is required")
    by_setting = {observation.setting_id: observation for observation in observations}
    unknown = set(by_setting) - {setting.setting_id for setting in settings}
    if unknown:
        raise ValueError(f"observations reference unknown settings: {sorted(unknown)}")
    usable = [
        observation for observation in observations
        if observation.recall is not None and observation.truncation_rate is not None
    ]
    if not usable:
        raise ValueError("no complete development observations")
    best_recall = max(observation.recall for observation in usable if observation.recall is not None)
    eligible = [
        setting for setting in settings
        if (observation := by_setting.get(setting.setting_id)) is not None
        and observation.recall is not None
        and observation.truncation_rate is not None
        and observation.recall >= best_recall - rule.recall_tolerance
        and observation.truncation_rate <= rule.max_truncation_rate
    ]
    if not eligible:
        raise ValueError("no calibration setting meets development selection rule")
    eligible.sort(key=lambda setting: (
        setting.estimated_cost_usd,
        -(by_setting[setting.setting_id].recall or 0.0),
        setting.setting_id,
    ))
    selected = eligible[0]
    decision_payload: dict[str, Any] = {
        "selected": selected.as_dict(),
        "eligible": [setting.as_dict() for setting in eligible],
        "best_development_recall": best_recall,
        "rule": {
            "recall_tolerance": rule.recall_tolerance,
            "max_truncation_rate": rule.max_truncation_rate,
            "development_only": rule.development_only,
        },
    }
    return SelectionDecision(
        selected.setting_id,
        tuple(setting.setting_id for setting in eligible),
        best_recall,
        rule,
        sha256_hex(decision_payload),
        selected,
        tuple(eligible),
        tuple(sorted(observations, key=lambda observation: observation.setting_id)),
    )


@dataclass(frozen=True, slots=True)
class BudgetInputs:
    campaign_count: int
    provider_calls_per_campaign: int
    expected_input_tokens: int
    expected_generated_tokens: int
    expected_retries_per_call: float = 0.0
    solver_core_seconds_per_campaign: float = 0.0
    baseline_campaign_count: int = 0
    calibration_campaign_count: int = 0
    adjudication_case_count: int = 0
    adjudication_seconds_per_case: float = 0.0
    input_cost_per_token: float | None = None
    generated_cost_per_token: float | None = None

    def __post_init__(self) -> None:
        if self.campaign_count <= 0 or self.provider_calls_per_campaign <= 0:
            raise ValueError("campaign and call counts must be positive")
        for name in ("expected_input_tokens", "expected_generated_tokens", "baseline_campaign_count", "calibration_campaign_count", "adjudication_case_count"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.expected_retries_per_call < 0 or self.solver_core_seconds_per_campaign < 0 or self.adjudication_seconds_per_case < 0:
            raise ValueError("budget rates must be non-negative")
        for name in ("input_cost_per_token", "generated_cost_per_token"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class BudgetEstimate:
    total_campaigns: int
    provider_calls: float
    input_tokens: int
    generated_tokens: int
    solver_core_hours: float
    adjudication_hours: float
    estimated_provider_cost_usd: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "total_campaigns": self.total_campaigns,
            "provider_calls": self.provider_calls,
            "input_tokens": self.input_tokens,
            "generated_tokens": self.generated_tokens,
            "solver_core_hours": self.solver_core_hours,
            "adjudication_hours": self.adjudication_hours,
            "estimated_provider_cost_usd": self.estimated_provider_cost_usd,
        }


def estimate_budget(inputs: BudgetInputs) -> BudgetEstimate:
    total_campaigns = inputs.campaign_count + inputs.baseline_campaign_count + inputs.calibration_campaign_count
    retry_multiplier = 1 + inputs.expected_retries_per_call
    provider_calls = total_campaigns * inputs.provider_calls_per_campaign * retry_multiplier
    # Token and cost estimates cover retry attempts as well as first attempts.
    # Ceil fractional expected totals so a planning budget never understates
    # provider consumption due to integer truncation.
    input_tokens = math.ceil(
        total_campaigns * inputs.provider_calls_per_campaign * inputs.expected_input_tokens * retry_multiplier
    )
    generated_tokens = math.ceil(
        total_campaigns * inputs.provider_calls_per_campaign * inputs.expected_generated_tokens * retry_multiplier
    )
    cost = None
    if inputs.input_cost_per_token is not None and inputs.generated_cost_per_token is not None:
        cost = input_tokens * inputs.input_cost_per_token + generated_tokens * inputs.generated_cost_per_token
    return BudgetEstimate(
        total_campaigns,
        provider_calls,
        input_tokens,
        generated_tokens,
        total_campaigns * inputs.solver_core_seconds_per_campaign / 3600,
        inputs.adjudication_case_count * inputs.adjudication_seconds_per_case / 3600,
        cost,
    )
