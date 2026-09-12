"""Shared candidate verification orchestration with fail-closed missingness."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .adapter import AdapterStatus, RuntimeCandidateAdapter, RuntimeCandidatePlan
from .cache import FileVerificationCache, VerificationCacheKey
from ..contracts.canonical import sha256_hex
from .records import CandidateInput, StageResult, StageStatus, VerificationOutcome
from .runtime import CaseRuntimeBindings


StageExecutor = Callable[[RuntimeCandidatePlan], StageResult]


@dataclass(frozen=True, slots=True)
class VerificationExecutors:
    """Optional backend hooks; all methods share the same plan input."""

    symbolic_search: StageExecutor | None = None
    witness_check: StageExecutor | None = None
    independent_replay: StageExecutor | None = None
    spec_hash: str | None = None
    deferred_runtime_fields: frozenset[str] = field(default_factory=frozenset)


class SharedVerificationPipeline:
    """Run grounding and the fixed downstream stage contract for any arm."""

    _DOWNSTREAM = ("symbolic_search", "witness_check", "independent_replay")

    def __init__(
        self,
        case: CaseRuntimeBindings,
        symbols: list[Any],
        *,
        executors: VerificationExecutors | None = None,
        cache: FileVerificationCache | None = None,
        adapter_revision: str = "runtime-adapter-v1",
        bounds: dict[str, Any] | None = None,
        replay_spec_hash: str | None = None,
        executor_spec_hash: str | None = None,
    ) -> None:
        self.executors = executors or VerificationExecutors()
        self.case = case
        self.adapter = RuntimeCandidateAdapter(
            case, symbols, adapter_revision=adapter_revision, bounds=bounds,
            replay_spec_hash=replay_spec_hash,
            deferred_runtime_fields=self.executors.deferred_runtime_fields,
        )
        effective_executor_spec_hash = executor_spec_hash
        if effective_executor_spec_hash is None and self.executors.spec_hash is not None:
            effective_executor_spec_hash = self.executors.spec_hash
        self.executor_spec_hash = effective_executor_spec_hash
        self.cache = cache

    def verify(self, candidate: CandidateInput) -> VerificationOutcome:
        plan = self.adapter.adapt(candidate)
        cache_key = self._cache_key(plan)
        if cache_key is not None and self.cache is not None:
            lookup = self.cache.lookup(cache_key)
            if lookup.hit and lookup.record is not None:
                raw_outcome = lookup.record.get("outcome")
                if not isinstance(raw_outcome, dict):
                    raise ValueError("verification cache entry has no outcome object")
                return VerificationOutcome.from_dict(candidate, raw_outcome, cache_hit=True)
        stages: list[StageResult] = [self._grounding_result(plan)]
        values: dict[str, bool | None] = {
            "candidate_violation": None,
            "property_holds": None,
            "security_relevance": None,
        }
        if stages[0].status is not StageStatus.PASSED:
            stages.extend(StageResult(name, StageStatus.NOT_APPLICABLE, "grounding_not_passed") for name in self._DOWNSTREAM)
        elif not plan.executable:
            # A typed predicate may be grounded while the case is still missing
            # addresses, actors, initialization, selectors, or other runtime
            # bindings.  Such a plan is useful audit output, but it must never
            # reach a backend callback that could accidentally turn metadata
            # coverage into an executable finding.
            stages.append(StageResult("symbolic_search", StageStatus.UNSUPPORTED, "runtime_binding_not_execution_ready"))
            stages.extend(
                StageResult(name, StageStatus.NOT_APPLICABLE, "symbolic_search_not_passed")
                for name in self._DOWNSTREAM[1:]
            )
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
            # ``property_holds`` is the concrete evaluator's truth value.  A
            # finding requires a witnessed violation, so the expected tuple is
            # candidate_violation=true, property_holds=false and
            # security_relevance=true.
            verified = (
                values["candidate_violation"] is True
                and values["property_holds"] is False
                and values["security_relevance"] is True
            )
        outcome = VerificationOutcome(
            candidate=candidate,
            stages=tuple(stages),
            candidate_violation=values["candidate_violation"],
            property_holds=values["property_holds"],
            security_relevance=values["security_relevance"],
            verified_finding=verified,
            first_failure=first_failure,
        )
        if cache_key is not None and self.cache is not None:
            self.cache.put(cache_key, outcome.as_dict())
        return outcome

    def _cache_key(self, plan: RuntimeCandidatePlan) -> VerificationCacheKey | None:
        if plan.canonical_ast_hash is None:
            return None
        return VerificationCacheKey(
            case_runtime_hash=self.case.runtime.runtime_hash,
            canonical_ast_hash=plan.canonical_ast_hash,
            adapter_revision=self.adapter.adapter_revision,
            bounds_hash=sha256_hex(self.adapter.bounds),
            replay_spec_hash=self.adapter.replay_spec_hash,
            executor_spec_hash=self.executor_spec_hash,
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
