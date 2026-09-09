"""Token-cap and usage validation without pretending to count unknown encodings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .ollama import ProviderResponse
from .tokenizer import TokenMeasurement


class BudgetStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TokenBudget:
    input_native_token_cap: int = 32768
    generated_native_token_cap: int = 8192

    def __post_init__(self) -> None:
        if self.input_native_token_cap <= 0 or self.generated_native_token_cap <= 0:
            raise ValueError("token caps must be positive")


@dataclass(frozen=True, slots=True)
class BudgetCheck:
    status: BudgetStatus
    prompt_tokens: int | None
    generated_tokens: int | None
    reason: str | None = None


def validate_usage(response: ProviderResponse, budget: TokenBudget | None = None) -> BudgetCheck:
    """Validate provider-reported usage; null usage is explicit UNKNOWN."""
    budget = budget or TokenBudget()
    prompt = response.usage.get("prompt_tokens")
    generated = response.usage.get("generated_tokens")
    if prompt is None or generated is None:
        return BudgetCheck(BudgetStatus.UNKNOWN, prompt, generated, "provider_usage_unavailable")
    if prompt > budget.input_native_token_cap:
        return BudgetCheck(BudgetStatus.FAIL, prompt, generated, "input_token_cap_exceeded")
    if generated > budget.generated_native_token_cap:
        return BudgetCheck(BudgetStatus.FAIL, prompt, generated, "generated_token_cap_exceeded")
    return BudgetCheck(BudgetStatus.PASS, prompt, generated)


def validate_measurement(measurement: TokenMeasurement, budget: TokenBudget | None = None) -> BudgetCheck:
    """Apply protocol caps to counts from an explicitly pinned tokenizer."""
    budget = budget or TokenBudget()
    prompt = measurement.prompt_tokens
    generated = measurement.generated_tokens
    if prompt is None or generated is None:
        return BudgetCheck(BudgetStatus.UNKNOWN, prompt, generated, "tokenizer_measurement_unavailable")
    if prompt > budget.input_native_token_cap:
        return BudgetCheck(BudgetStatus.FAIL, prompt, generated, "input_token_cap_exceeded")
    if generated > budget.generated_native_token_cap:
        return BudgetCheck(BudgetStatus.FAIL, prompt, generated, "generated_token_cap_exceeded")
    return BudgetCheck(BudgetStatus.PASS, prompt, generated)
