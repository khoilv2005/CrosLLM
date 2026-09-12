"""Development fixture executors for the shared verification pipeline.

This module connects a grounded candidate to the existing bounded paired-chain
explorer and native witness checker.  It is deliberately explicit about its
boundary: the fixture is not an EVM implementation.  A separately supplied
callback is required for the independent replay stage.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..backends import SymbolicPairedExplorer, SymbolicSearchControl, SymbolicSearchResult
from ..contracts.records import SearchStatus
from ..replay import NativeReplay, Witness, WitnessProjector
from ..replay.witness import replay_action_records
from ..semantics import DualChainState, Message, PairedFixture
from ..xlir.evaluator import EvaluationError, evaluate_invariant
from ..xlir.model import Binary, BoundRef, Expression, Invariant, Quantifier, SymbolRef, Temporal, Unary
from .adapter import RuntimeCandidatePlan
from .pipeline import StageExecutor, VerificationExecutors
from .records import StageResult, StageStatus


StateReader = Callable[[DualChainState], object]
IndependentReplay = Callable[[RuntimeCandidatePlan, Witness], StageResult]


@dataclass(frozen=True, slots=True)
class FixtureVerificationConfig:
    """Explicit development-only inputs for one fixture verification worker."""

    fixture: PairedFixture
    messages: tuple[Message, ...]
    state_readers: Mapping[tuple[str, str, str], StateReader]
    created_at: str = "1970-01-01T00:00:00+00:00"

    def __post_init__(self) -> None:
        if not isinstance(self.fixture, PairedFixture):
            raise ValueError("fixture must be a PairedFixture")
        if not isinstance(self.messages, tuple):
            raise ValueError("messages must be a tuple")
        if not isinstance(self.state_readers, Mapping):
            raise ValueError("state_readers must be a mapping")
        if any(not callable(reader) for reader in self.state_readers.values()):
            raise ValueError("every state reader must be callable")
        if not self.created_at:
            raise ValueError("created_at is required")


class FixtureVerificationExecutors:
    """Connect the common pipeline to bounded fixture search and replay."""

    def __init__(
        self,
        config: FixtureVerificationConfig,
        *,
        independent_replay: IndependentReplay | None = None,
    ) -> None:
        self.config = config
        self.independent_replay_callback = independent_replay
        self._search_results: dict[str, SymbolicSearchResult] = {}
        self._witnesses: dict[str, Witness] = {}
        self._initial_state = config.fixture.snapshot()

    def executors(self) -> VerificationExecutors:
        return VerificationExecutors(
            symbolic_search=self.symbolic_search,
            witness_check=self.witness_check,
            independent_replay=self.independent_replay,
        )

    def symbolic_search(self, plan: RuntimeCandidatePlan) -> StageResult:
        if plan.invariant is None or not plan.executable:
            return StageResult("symbolic_search", StageStatus.UNSUPPORTED, "runtime_plan_not_executable")
        missing = self._missing_readers(plan.invariant)
        if missing:
            return StageResult(
                "symbolic_search", StageStatus.UNSUPPORTED,
                "state_reader_missing:" + ",".join(missing),
            )
        try:
            explorer = SymbolicPairedExplorer(self.config.messages)
            result = explorer.search(
                self.config.fixture,
                lambda state: not self._evaluate(plan.invariant, state),
                control=self._control(plan),
            )
        except Exception as error:
            return StageResult("symbolic_search", StageStatus.CRASH, f"fixture_search_crash:{type(error).__name__}:{error}")
        self._search_results[self._key(plan)] = result
        status = _search_stage_status(result)
        evidence: dict[str, object] = {
            "search_status": result.status.value,
            "complete": result.complete,
            "explored_states": result.explored_states,
            "explored_paths": result.explored_paths,
            "schedule_count": result.schedule_count,
            "elapsed_seconds": result.elapsed_seconds,
            "encoding_hash": result.encoding_hash,
        }
        if result.status is SearchStatus.SAT and result.complete:
            evidence["candidate_violation"] = True
        elif result.status is SearchStatus.BOUNDED_UNSAT and result.complete:
            evidence["candidate_violation"] = False
        return StageResult("symbolic_search", status, result.reason if status is not StageStatus.PASSED else None, result.elapsed_seconds, evidence)

    def witness_check(self, plan: RuntimeCandidatePlan) -> StageResult:
        result = self._search_results.get(self._key(plan))
        if result is None:
            return StageResult("witness_check", StageStatus.NOT_APPLICABLE, "symbolic_result_missing")
        if result.status is not SearchStatus.SAT or not result.complete:
            return StageResult("witness_check", StageStatus.NOT_APPLICABLE, "no_complete_sat_witness")
        if plan.invariant is None:
            return StageResult("witness_check", StageStatus.UNSUPPORTED, "invariant_missing")
        try:
            witness = WitnessProjector().project(
                result,
                self.config.fixture,
                witness_id=f"witness:{self._key(plan)}",
                query_id=f"query:{self._key(plan)}",
                created_at=self.config.created_at,
            )
            native = NativeReplay().check(witness, self.config.fixture)
            if native.status.value != "pass":
                return StageResult(
                    "witness_check", StageStatus.FAILED,
                    native.reason or "native_replay_failed",
                    evidence={"native_replay_status": native.status.value},
                )
            final_fixture = replay_action_records(self.config.fixture, tuple(
                _action_from_dict(row) for row in witness.actions
            ))
            property_holds = self._evaluate(plan.invariant, final_fixture.state)
            if property_holds:
                return StageResult("witness_check", StageStatus.FAILED, "witness_does_not_violate_property")
            self._witnesses[self._key(plan)] = witness
            return StageResult(
                "witness_check", StageStatus.PASSED,
                elapsed_seconds=0.0,
                evidence={
                    "candidate_violation": True,
                    "property_holds": False,
                    "native_replay_status": native.status.value,
                    "witness_id": witness.witness_id,
                    "trace_hash": witness.trace_hash,
                },
            )
        except (EvaluationError, ValueError, TypeError, KeyError) as error:
            return StageResult("witness_check", StageStatus.CRASH, f"witness_check_failure:{type(error).__name__}:{error}")

    def independent_replay(self, plan: RuntimeCandidatePlan) -> StageResult:
        witness = self._witnesses.get(self._key(plan))
        if witness is None:
            return StageResult("independent_replay", StageStatus.NOT_APPLICABLE, "witness_missing")
        if self.independent_replay_callback is None:
            return StageResult("independent_replay", StageStatus.UNSUPPORTED, "independent_replay_callback_not_configured")
        try:
            result = self.independent_replay_callback(plan, witness)
        except Exception as error:
            return StageResult("independent_replay", StageStatus.CRASH, f"independent_replay_crash:{type(error).__name__}:{error}")
        if result.stage != "independent_replay":
            return StageResult("independent_replay", StageStatus.CRASH, "independent_replay_stage_mismatch")
        return result

    def _evaluate(self, invariant: Invariant, state: DualChainState) -> bool:
        if _contains_temporal(invariant.body):
            raise EvaluationError("fixture executor does not support temporal observations")
        bindings = {
            key: reader(state if key[1] == "post" else _state_from_snapshot(self._initial_state))
            for key, reader in self.config.state_readers.items()
        }
        return evaluate_invariant(invariant, bindings)

    def _missing_readers(self, invariant: Invariant) -> tuple[str, ...]:
        missing = {
            f"{reference.symbol_id}|{reference.state}|{reference.domain}"
            for reference in _symbol_references(invariant.body)
            if (reference.symbol_id, reference.state, reference.domain) not in self.config.state_readers
        }
        return tuple(sorted(missing))

    @staticmethod
    def _key(plan: RuntimeCandidatePlan) -> str:
        return plan.cache_key or plan.canonical_ast_hash or plan.candidate.slot_id

    @staticmethod
    def _control(plan: RuntimeCandidatePlan) -> SymbolicSearchControl:
        bounds = plan.search_request.get("bounds", {}) if plan.search_request is not None else {}
        if not isinstance(bounds, Mapping):
            bounds = {}
        return SymbolicSearchControl(
            query_timeout_seconds=_positive_number(bounds.get("query_timeout_seconds", 30.0), "query_timeout_seconds"),
            campaign_deadline_seconds=_positive_number(bounds.get("campaign_deadline_seconds", 3600.0), "campaign_deadline_seconds"),
            campaign_elapsed_seconds=_nonnegative_number(bounds.get("campaign_elapsed_seconds", 0.0), "campaign_elapsed_seconds"),
            max_models=_positive_int(bounds.get("max_models", 100_000), "max_models"),
        )


def _search_stage_status(result: SymbolicSearchResult) -> StageStatus:
    if result.status in {SearchStatus.SAT, SearchStatus.BOUNDED_UNSAT} and result.complete:
        return StageStatus.PASSED
    return {
        SearchStatus.UNKNOWN: StageStatus.UNKNOWN,
        SearchStatus.TIMEOUT: StageStatus.TIMEOUT,
        SearchStatus.UNSUPPORTED: StageStatus.UNSUPPORTED,
        SearchStatus.CRASH: StageStatus.CRASH,
    }.get(result.status, StageStatus.UNKNOWN)


def _contains_temporal(expression: Expression) -> bool:
    if isinstance(expression, Temporal):
        return True
    if isinstance(expression, (Unary,)):
        return _contains_temporal(expression.operand)
    if isinstance(expression, Binary):
        return _contains_temporal(expression.left) or _contains_temporal(expression.right)
    if isinstance(expression, Quantifier):
        return _contains_temporal(expression.body)
    return False


def _symbol_references(expression: Expression) -> tuple[SymbolRef, ...]:
    found: dict[tuple[str, str, str], SymbolRef] = {}

    def visit(node: Expression) -> None:
        if isinstance(node, SymbolRef):
            found[(node.symbol_id, node.state, node.domain)] = node
        elif isinstance(node, (Unary, Temporal)):
            visit(node.operand)
        elif isinstance(node, Binary):
            visit(node.left)
            visit(node.right)
        elif isinstance(node, Quantifier):
            visit(node.body)
        elif isinstance(node, BoundRef):
            return

    visit(expression)
    return tuple(found[key] for key in sorted(found))


def _state_from_snapshot(snapshot: DualChainState) -> DualChainState:
    from copy import deepcopy

    return deepcopy(snapshot)


def _action_from_dict(row: Mapping[str, Any]):
    from ..replay.witness import action_from_dict

    return action_from_dict(dict(row))


def _positive_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{field} must be positive")
    return float(value)


def _nonnegative_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{field} must be non-negative")
    return float(value)


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


__all__ = ["FixtureVerificationConfig", "FixtureVerificationExecutors", "IndependentReplay", "StateReader"]
