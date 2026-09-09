"""Development method runners sharing the same provider/slot contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Callable

from ..providers import (
    BudgetCheck,
    ExactTokenCounter,
    OllamaClient,
    ProviderRequest,
    TokenBudget,
    TokenMeasurement,
    validate_usage,
    validate_measurement,
)
from .proposal import OrderedProposalSlots, PromptTemplate, ProposalSlotStatus, candidate_identity, classify_response


class MethodTrack(StrEnum):
    CROSSLLM = "X"
    DIRECT = "P"
    T0 = "T0"


@dataclass(frozen=True, slots=True)
class MethodRun:
    track: MethodTrack
    backbone: str
    attempt_id: str
    template_hash: str
    artifact_pack_hash: str
    settings: dict[str, object]
    slots: tuple[object, ...]
    provider_responses: tuple[object, ...] = ()
    token_measurements: tuple[TokenMeasurement, ...] = ()
    budget_checks: tuple[BudgetCheck, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "track": self.track,
            "backbone": self.backbone,
            "attempt_id": self.attempt_id,
            "template_hash": self.template_hash,
            "artifact_pack_hash": self.artifact_pack_hash,
            "settings": self.settings,
            "slots": [slot.as_dict() if hasattr(slot, "as_dict") else slot for slot in self.slots],
            "provider_responses": [response.as_dict() if hasattr(response, "as_dict") else response for response in self.provider_responses],
            "token_measurements": [measurement.as_dict() for measurement in self.token_measurements],
            "budget_checks": [
                {
                    "status": check.status.value,
                    "prompt_tokens": check.prompt_tokens,
                    "generated_tokens": check.generated_tokens,
                    "reason": check.reason,
                }
                for check in self.budget_checks
            ],
        }


CandidateParser = Callable[[str], object | None]


class MethodRunner:
    """Run exactly one ordered slot sequence with a stateless provider client."""

    def __init__(
        self,
        client: OllamaClient,
        *,
        proposal_slots: int = 8,
        token_counter: ExactTokenCounter | None = None,
        token_budget: TokenBudget | None = None,
    ) -> None:
        if proposal_slots <= 0:
            raise ValueError("proposal_slots must be positive")
        self.client = client
        self.proposal_slots = proposal_slots
        self.token_counter = token_counter
        self.token_budget = token_budget or TokenBudget()

    def run(
        self,
        *,
        track: MethodTrack,
        backbone: str,
        model: str,
        attempt_id: str,
        template: PromptTemplate,
        artifact_pack_text: str,
        artifact_pack_hash: str,
        settings: dict[str, object],
        parse_candidate: CandidateParser | None = None,
        expected_response_model: str | None = None,
        cancelled: Callable[[], bool] | None = None,
        campaign_deadline_seconds: float | None = None,
    ) -> MethodRun:
        if not backbone or not model or not artifact_pack_hash:
            raise ValueError("backbone, model and artifact_pack_hash are required")
        if expected_response_model is not None and not expected_response_model:
            raise ValueError("expected_response_model must be non-empty when provided")
        if template.policy.proposal_slots != self.proposal_slots:
            raise ValueError("template and runner slot counts must match")
        prompt = template.render(artifact_pack_text)
        slots = OrderedProposalSlots(attempt_id, policy=template.policy)
        responses = []
        provider_responses = []
        measurements: list[TokenMeasurement] = []
        budget_checks: list[BudgetCheck] = []
        candidate_hashes: set[str] = set()
        parser = parse_candidate or (lambda _text: None)
        for index in range(self.proposal_slots):
            response = self.client.propose(
                ProviderRequest(model, prompt, dict(settings)),
                cancelled=cancelled,
                campaign_deadline_seconds=campaign_deadline_seconds,
            )
            provider_responses.append(response)
            candidate = None
            model_identity_mismatch = (
                expected_response_model is not None
                and response.error is None
                and response.response_model != expected_response_model
            )
            if (
                not model_identity_mismatch
                and response.ok
                and not response.partial
                and response.response_text is not None
            ):
                try:
                    candidate = parser(response.response_text)
                except (ValueError, TypeError):
                    candidate = None
            if model_identity_mismatch:
                status, classified_candidate, reason = (
                    ProposalSlotStatus.PROVIDER_FAILURE,
                    None,
                    "response_model_mismatch",
                )
            else:
                status, classified_candidate, reason = classify_response(response, candidate)
            candidate_hash: str | None = None
            canonical_ast_hash: str | None = None
            if classified_candidate is not None:
                try:
                    candidate_hash, canonical_ast_hash = candidate_identity(classified_candidate)
                except (TypeError, ValueError):
                    candidate_hash = None
                    canonical_ast_hash = None
                if candidate_hash is not None:
                    if candidate_hash in candidate_hashes:
                        status, classified_candidate, reason = ProposalSlotStatus.DUPLICATE, None, "duplicate_candidate"
            # Ollama's native usage fields are the first cap check whenever
            # they are available.  This must happen even without a local
            # tokenizer: otherwise a live response can exceed the protocol
            # cap while producing an empty budget ledger.
            budget_check = validate_usage(response, self.token_budget)
            if self.token_counter is not None:
                measurement = self.token_counter.measure(prompt, response.response_text)
                measurement_check = validate_measurement(measurement, self.token_budget)
                measurements.append(measurement)
                if measurement_check.status.value == "fail":
                    budget_check = measurement_check
                elif budget_check.status.value != "fail":
                    budget_check = measurement_check
            budget_checks.append(budget_check)
            if (
                budget_check.status.value == "fail"
                and status not in {ProposalSlotStatus.DUPLICATE, ProposalSlotStatus.PROVIDER_FAILURE}
            ):
                status, classified_candidate, reason = ProposalSlotStatus.INVALID, None, budget_check.reason
            elif candidate_hash is not None and status is ProposalSlotStatus.CANDIDATE:
                # A candidate rejected by a protocol budget is not an accepted
                # candidate and must not poison duplicate detection for later
                # ordered slots carrying the same payload.
                candidate_hashes.add(candidate_hash)
            slots.record(
                index,
                status,
                raw_response_hash=response.response_hash,
                candidate=classified_candidate,
                reason=reason,
                canonical_ast_hash=(canonical_ast_hash if status in {
                    ProposalSlotStatus.CANDIDATE, ProposalSlotStatus.DUPLICATE,
                } else None),
            )
            responses.append(slots.slots[index])
        return MethodRun(
            track, backbone, attempt_id, template.template_hash, artifact_pack_hash,
            dict(settings), tuple(responses), tuple(provider_responses),
            tuple(measurements), tuple(budget_checks),
        )
