"""Finite antecedent reachability checks for implication-shaped invariants."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from .evaluator import EvaluationError, StateBindings, TraceBindings, evaluate_expression
from .model import Binary, Invariant

if TYPE_CHECKING:
    from ..backends.smt import SMTControl, Z3XLIRBackend


class VacuityStatus(StrEnum):
    REACHABLE = "reachable"
    BOUNDED_UNSAT = "bounded_unsat"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class VacuityResult:
    status: VacuityStatus
    checked_bindings: int
    complete: bool
    reason: str | None = None


def check_antecedent(
    invariant: Invariant,
    bindings: Iterable[StateBindings],
    *,
    exhaustive: bool,
) -> VacuityResult:
    """Check whether a root implication antecedent is reachable in a finite set.

    ``exhaustive=False`` makes an all-false sample `UNKNOWN`; it can never be
    upgraded to a bounded proof merely because the sample happened to be empty.
    Binding/type errors are also `UNKNOWN`, never evidence of unreachable state.
    """

    if not isinstance(invariant.body, Binary) or invariant.body.operator != "implies":
        return VacuityResult(VacuityStatus.NOT_APPLICABLE, 0, True, "root_is_not_implication")
    checked = 0
    for binding in bindings:
        checked += 1
        try:
            if evaluate_expression(invariant.body.left, binding):
                return VacuityResult(VacuityStatus.REACHABLE, checked, exhaustive, "antecedent_satisfied")
        except EvaluationError as error:
            return VacuityResult(VacuityStatus.UNKNOWN, checked, False, f"binding_error:{error}")
    if exhaustive:
        return VacuityResult(VacuityStatus.BOUNDED_UNSAT, checked, True, "finite_bindings_exhausted")
    return VacuityResult(VacuityStatus.UNKNOWN, checked, False, "binding_sample_not_exhaustive")


def check_antecedent_transition(
    invariant: Invariant,
    traces: Iterable[TraceBindings],
    *,
    exhaustive: bool,
    transition_complete: bool,
) -> VacuityResult:
    """Check antecedent reachability over traces emitted by a transition model.

    A finite collection of arbitrary state bindings is not transition evidence:
    it can miss ordering, clocks, delivery and reorg constraints.  This API
    therefore requires explicit transition traces and a separate completeness
    declaration before it can return ``BOUNDED_UNSAT``.  Empty traces and
    evaluator errors remain ``UNKNOWN`` to prevent vacuity-by-construction.
    """
    if not isinstance(invariant.body, Binary) or invariant.body.operator != "implies":
        return VacuityResult(VacuityStatus.NOT_APPLICABLE, 0, True, "root_is_not_implication")
    if not isinstance(exhaustive, bool) or not isinstance(transition_complete, bool):
        raise ValueError("exhaustive and transition_complete must be boolean")
    checked = 0
    saw_trace = False
    for trace in traces:
        checked += 1
        if not isinstance(trace, Sequence) or not trace:
            return VacuityResult(VacuityStatus.UNKNOWN, checked, False, "missing_transition_trace")
        saw_trace = True
        try:
            if evaluate_expression(invariant.body.left, trace[0], trace=trace, index=0):
                return VacuityResult(
                    VacuityStatus.REACHABLE,
                    checked,
                    exhaustive and transition_complete,
                    "transition_trace_antecedent_satisfied",
                )
        except EvaluationError as error:
            return VacuityResult(VacuityStatus.UNKNOWN, checked, False, f"transition_trace_error:{error}")
    if not saw_trace:
        return VacuityResult(VacuityStatus.UNKNOWN, 0, False, "no_transition_traces")
    if exhaustive and transition_complete:
        return VacuityResult(VacuityStatus.BOUNDED_UNSAT, checked, True, "transition_trace_space_exhausted")
    return VacuityResult(VacuityStatus.UNKNOWN, checked, False, "transition_trace_set_not_complete")


def check_antecedent_smt(
    invariant: Invariant,
    *,
    backend: Z3XLIRBackend | None = None,
    control: SMTControl | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> VacuityResult:
    """Check implication antecedent reachability with the grounded SMT core.

    This preserves the finite-binding API's vacuity vocabulary while making the
    solver's operational outcomes explicit in ``reason``. A solver result is
    never interpreted as a security-legitimacy judgment.
    """
    if not isinstance(invariant.body, Binary) or invariant.body.operator != "implies":
        return VacuityResult(VacuityStatus.NOT_APPLICABLE, 0, True, "root_is_not_implication")
    from ..backends.smt import Z3XLIRBackend

    result = (backend or Z3XLIRBackend()).check_antecedent(
        invariant,
        control=control,
        cancelled=cancelled,
    )
    if result.status.value == "sat":
        return VacuityResult(VacuityStatus.REACHABLE, 0, result.complete, "solver_antecedent_satisfied")
    if result.status.value == "bounded_unsat":
        return VacuityResult(VacuityStatus.BOUNDED_UNSAT, 0, result.complete, "solver_formula_exhausted")
    return VacuityResult(VacuityStatus.UNKNOWN, 0, False, f"solver_{result.status.value}:{result.reason}")
