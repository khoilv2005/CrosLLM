"""Shared candidate verification orchestration with fail-closed missingness."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .adapter import AdapterStatus, RuntimeCandidateAdapter, RuntimeCandidatePlan
from .records import CandidateInput, StageResult, StageStatus, VerificationOutcome
from .runtime import CaseRuntimeBindings


StageExecutor = Callable[[RuntimeCandidatePlan], StageResult]


@dataclass(frozen=True, slots=True)
class VerificationExecutors:
    """Optional backend hooks; all methods share the same plan input."""

    symbolic_search: StageExecutor | None = None
    witness_check: StageExecutor | None = None
    independent_replay: StageExecutor | None = None


class SharedVerificationPipeline:
    """Run grounding and the fixed downstream stage contract for any arm."""

    _DOWNSTREAM = ("symbolic_search", "witness_check", "independent_replay")

    def __init__(self, case: CaseRuntimeBindings, symbols: list[Any], *, executors: VerificationExecutors | None = None) -> None:
        self.case = case
        self.adapter = RuntimeCandidateAdapter(case, symbols)
        self.executors = executors or VerificationExecutors()

    def verify(self, candidate: CandidateInput) -> VerificationOutcome:
        plan = self.adapter.adapt(candidate)
        stages: list[StageResult] = [self._grounding_result(plan)]
        values: dict[str, bool | None] = {
            "candidate_violation": None,
            "property_holds": None,
            "security_relevance": None,
        }
        if stages[0].status is not StageStatus.PASSED:
            stages.extend(StageResult(name, StageStatus.NOT_APPLICABLE, "grounding_not_passed") for name in self._DOWNSTREAM)
        else:
            for name in self._DOWNSTREAM:
                stage = self._run_stage(name, plan)
                stages.append(stage)
                if stage.evidence is not None:
                    for field in values:
                        value = stage.evidence.get(field)
                        if isinstance(value, bool):
                            values[field] = value
                if stage.status is not StageStatus.PASSED:
                    stages.extend(
                        StageResult(later, StageStatus.NOT_APPLICABLE, f"{name}_not_passed")
                        for later in self._DOWNSTREAM[self._DOWNSTREAM.index(name) + 1:]
                    )
                    break
        first_failure = next((stage.stage for stage in stages if stage.status not in {StageStatus.PASSED, StageStatus.NOT_APPLICABLE}), None)
        all_required_passed = all(next(stage for stage in stages if stage.stage == name).status is StageStatus.PASSED for name in ("grounding", *self._DOWNSTREAM))
        verified: bool | None = None
        if all_required_passed:
            verified = all(values[field] is True for field in values)
        return VerificationOutcome(
            candidate=candidate,
            stages=tuple(stages),
            candidate_violation=values["candidate_violation"],
            property_holds=values["property_holds"],
            security_relevance=values["security_relevance"],
            verified_finding=verified,
            first_failure=first_failure,
        )

    @staticmethod
    def _grounding_result(plan: RuntimeCandidatePlan) -> StageResult:
        if plan.status in {AdapterStatus.GROUNDED, AdapterStatus.READY}:
            return StageResult(
                "grounding", StageStatus.PASSED,
                evidence={"canonical_ast_hash": plan.canonical_ast_hash, "adapter_status": plan.status.value},
            )
        if plan.status is AdapterStatus.ABSTAINED:
            return StageResult("grounding", StageStatus.NOT_APPLICABLE, "proposal_abstained")
        if plan.status is AdapterStatus.INVALID:
            return StageResult("grounding", StageStatus.FAILED, ";".join(plan.diagnostics) or "xlir_invalid")
        return StageResult("grounding", StageStatus.UNSUPPORTED, ";".join(plan.diagnostics) or "runtime_binding_unsupported")

    def _run_stage(self, name: str, plan: RuntimeCandidatePlan) -> StageResult:
        executor = getattr(self.executors, name)
        if executor is None:
            return StageResult(name, StageStatus.UNSUPPORTED, f"{name}_executor_not_configured")
        try:
            result = executor(plan)
        except Exception as error:  # backend faults must remain candidate-level crash states
            return StageResult(name, StageStatus.CRASH, f"{name}_executor_crash:{error}")
        if not isinstance(result, StageResult):
            return StageResult(name, StageStatus.CRASH, f"{name}_executor_returned_invalid_result")
        if result.stage != name:
            return StageResult(name, StageStatus.CRASH, f"{name}_executor_stage_mismatch")
        return result


__all__ = ["SharedVerificationPipeline", "VerificationExecutors"]
