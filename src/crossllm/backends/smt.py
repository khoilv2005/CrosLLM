"""Z3-backed execution for the grounded XLIR core.

This adapter executes the finite XLIR core after explicit finite quantifier
expansion and temporal indexing. It proves/query-checks only the supplied
formula; it does not model EVM transactions or claim deployment-level
completeness.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
import time
import z3

from ..contracts.canonical import sha256_hex
from ..contracts.records import SearchStatus
from ..xlir.model import Binary, BoundRef, Expression, Invariant, Literal, Quantifier, SymbolRef, Temporal, Unary, ValueType
from .solver_control import check_solver


@dataclass(frozen=True, slots=True)
class SMTControl:
    timeout_seconds: float = 30.0
    campaign_deadline_seconds: float = 3600.0
    campaign_elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.timeout_seconds)
            or not math.isfinite(self.campaign_deadline_seconds)
            or not math.isfinite(self.campaign_elapsed_seconds)
        ):
            raise ValueError("SMT deadlines must be finite")
        if self.timeout_seconds <= 0 or self.campaign_deadline_seconds <= 0:
            raise ValueError("SMT deadlines must be positive")
        if self.timeout_seconds > self.campaign_deadline_seconds:
            raise ValueError("SMT timeout cannot exceed campaign deadline")
        if self.campaign_elapsed_seconds < 0:
            raise ValueError("campaign elapsed time cannot be negative")

    def remaining_seconds(self) -> float:
        """Return the budget available to this query after prior campaign work."""

        return min(
            self.timeout_seconds,
            max(0.0, self.campaign_deadline_seconds - self.campaign_elapsed_seconds),
        )

    def expiration_reason(self, elapsed_seconds: float) -> str:
        if self.campaign_elapsed_seconds + elapsed_seconds >= self.campaign_deadline_seconds:
            return "campaign_deadline"
        return "query_timeout"


@dataclass(frozen=True, slots=True)
class SMTResult:
    status: SearchStatus
    complete: bool
    model: dict[str, object]
    reason: str | None
    elapsed_seconds: float
    solver: str
    query_hash: str
    explored_states: int = 0
    explored_paths: int = 0
    schedule_count: int = 0
    cache_hits: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "complete": self.complete,
            "model": self.model,
            "reason": self.reason,
            "elapsed_seconds": self.elapsed_seconds,
            "solver": self.solver,
            "query_hash": self.query_hash,
            "explored_states": self.explored_states,
            "explored_paths": self.explored_paths,
            "schedule_count": self.schedule_count,
            "cache_hits": self.cache_hits,
        }


class Z3XLIRBackend:
    """Solve counterexample and antecedent queries over an XLIR invariant."""

    _sorts = {
        ValueType.BOOL: z3.BoolSort(),
        ValueType.UINT256: z3.BitVecSort(256),
        ValueType.INT256: z3.BitVecSort(256),
        ValueType.ADDRESS: z3.BitVecSort(160),
        ValueType.BYTES32: z3.BitVecSort(256),
    }

    def check_violation(
        self,
        invariant: Invariant,
        *,
        control: SMTControl | None = None,
        cancelled: Callable[[], bool] | None = None,
        trace_length: int | None = None,
    ) -> SMTResult:
        return self._check(invariant, "violation", control, cancelled, trace_length)

    def check_antecedent(
        self,
        invariant: Invariant,
        *,
        control: SMTControl | None = None,
        cancelled: Callable[[], bool] | None = None,
        trace_length: int | None = None,
    ) -> SMTResult:
        if not isinstance(invariant.body, Binary) or invariant.body.operator != "implies":
            return SMTResult(
                SearchStatus.UNSUPPORTED,
                False,
                {},
                "root_is_not_implication",
                0.0,
                self._solver_name(),
                sha256_hex({"invariant": invariant.canonical_hash, "query": "antecedent"}),
            )
        return self._check(invariant, "antecedent", control, cancelled, trace_length)

    def _check(
        self,
        invariant: Invariant,
        query_name: str,
        control: SMTControl | None,
        cancelled: Callable[[], bool] | None,
        trace_length: int | None,
    ) -> SMTResult:
        control = control or SMTControl()
        started = time.monotonic()
        if control.remaining_seconds() <= 0:
            return self._result(SearchStatus.TIMEOUT, False, {}, "campaign_deadline", started, sha256_hex({
                "invariant": invariant.canonical_hash,
                "query": query_name,
                "timeout_seconds": control.timeout_seconds,
                "campaign_deadline_seconds": control.campaign_deadline_seconds,
                "campaign_elapsed_seconds": control.campaign_elapsed_seconds,
                "solver": self._solver_name(),
                "encoding": "xlir-finite-temporal-v4-checked-arithmetic-and-bitvectors",
                "trace_length": trace_length,
            }))
        query_hash = sha256_hex({
            "invariant": invariant.canonical_hash,
            "query": query_name,
            "timeout_seconds": control.timeout_seconds,
            "campaign_deadline_seconds": control.campaign_deadline_seconds,
            "campaign_elapsed_seconds": control.campaign_elapsed_seconds,
            "solver": self._solver_name(),
            "encoding": "xlir-finite-temporal-v4-checked-arithmetic-and-bitvectors",
            "trace_length": trace_length,
        })
        if cancelled is not None:
            try:
                if cancelled():
                    return self._result(SearchStatus.UNKNOWN, False, {}, "cancelled", started, query_hash)
            except Exception as error:
                return self._result(SearchStatus.CRASH, False, {}, f"cancellation_error:{error}", started, query_hash)
        variables: dict[str, tuple[z3.ExprRef, ValueType]] = {}
        constraints: list[z3.BoolRef] = []
        try:
            expression = invariant.body
            if query_name == "antecedent":
                if not isinstance(invariant.body, Binary):
                    raise ValueError("antecedent query requires an implication")
                expression = invariant.body.left
            translated = self._translate(
                expression,
                variables,
                constraints,
                trace_length=trace_length,
            )
            query = translated if query_name == "antecedent" else z3.Not(translated)
        except (TypeError, ValueError, z3.Z3Exception) as error:
            if isinstance(error, ValueError) and str(error) in {
                "temporal translation requires positive trace_length",
            }:
                return self._result(SearchStatus.UNSUPPORTED, False, {}, "trace_length_required", started, query_hash)
            return self._result(SearchStatus.CRASH, False, {}, f"translation_error:{error}", started, query_hash)
        solver = z3.Solver()
        query_budget = control.remaining_seconds()
        solver.set(timeout=max(1, int(query_budget * 1000)))
        solver.add(*constraints)
        solver.add(query)
        try:
            solver_check = check_solver(solver, cancelled)
        except z3.Z3Exception as error:
            return self._result(SearchStatus.CRASH, False, {}, f"solver_error:{error}", started, query_hash)
        if solver_check.callback_error is not None:
            return self._result(SearchStatus.CRASH, False, {}, f"cancellation_error:{solver_check.callback_error}", started, query_hash)
        if solver_check.interrupted:
            return self._result(SearchStatus.UNKNOWN, False, {}, "cancelled", started, query_hash)
        checked = solver_check.result
        if cancelled is not None:
            try:
                if cancelled():
                    return self._result(SearchStatus.UNKNOWN, False, {}, "cancelled", started, query_hash)
            except Exception as error:
                return self._result(SearchStatus.CRASH, False, {}, f"cancellation_error:{error}", started, query_hash)
        if checked == z3.sat:
            model = solver.model()
            return self._result(SearchStatus.SAT, True, self._model_values(model, variables), None, started, query_hash)
        if checked == z3.unsat:
            return self._result(
                SearchStatus.BOUNDED_UNSAT,
                True,
                {},
                "finite_xlir_formula_exhausted",
                started,
                query_hash,
            )
        elapsed = time.monotonic() - started
        reason_unknown = solver.reason_unknown() or "solver_unknown"
        if elapsed >= query_budget or "timeout" in reason_unknown.lower():
            return self._result(
                SearchStatus.TIMEOUT,
                False,
                {},
                control.expiration_reason(elapsed),
                started,
                query_hash,
            )
        return self._result(SearchStatus.UNKNOWN, False, {}, reason_unknown, started, query_hash)

    @staticmethod
    def _translate(
        expression: Expression,
        variables: dict[str, tuple[z3.ExprRef, ValueType]],
        constraints: list[z3.BoolRef],
        *,
        trace_length: int | None = None,
        index: int = 0,
        bound: dict[str, z3.ExprRef] | None = None,
    ) -> z3.ExprRef:
        bound = bound or {}
        if isinstance(expression, SymbolRef):
            key = f"{expression.symbol_id}|{expression.state}|{expression.domain}"
            if trace_length is not None:
                key = f"{key}|trace_index={index}"
            if key not in variables:
                variables[key] = (z3.Const(f"s_{sha256_hex(key)[:16]}", Z3XLIRBackend._sorts[expression.value_type]), expression.value_type)
            return variables[key][0]
        if isinstance(expression, BoundRef):
            if expression.variable not in bound:
                raise ValueError(f"unresolved bound variable {expression.variable!r}")
            return bound[expression.variable]
        if isinstance(expression, Literal):
            if expression.value_type is ValueType.BOOL:
                return z3.BoolVal(expression.value)
            return z3.BitVecVal(
                int(expression.value, 16) if isinstance(expression.value, str) else expression.value,
                Z3XLIRBackend._sorts[expression.value_type].size(),
            )
        if isinstance(expression, Quantifier):
            terms: list[z3.ExprRef] = []
            for literal in expression.domain:
                scoped = dict(bound)
                scoped[expression.variable] = Z3XLIRBackend._translate(
                    literal,
                    variables,
                    constraints,
                    trace_length=trace_length,
                    index=index,
                    bound=bound,
                )
                terms.append(
                    Z3XLIRBackend._translate(
                        expression.body,
                        variables,
                        constraints,
                        trace_length=trace_length,
                        index=index,
                        bound=scoped,
                    )
                )
            if expression.operator == "forall":
                return z3.And(*terms) if terms else z3.BoolVal(True)
            if expression.operator == "exists":
                return z3.Or(*terms) if terms else z3.BoolVal(False)
            raise ValueError("unsupported quantifier operator")
        if isinstance(expression, Temporal):
            if trace_length is None or trace_length <= 0:
                raise ValueError("temporal translation requires positive trace_length")
            if expression.operator == "once":
                assert expression.horizon is not None
                positions = range(max(0, index - expression.horizon), index + 1)
                operator = z3.Or
            elif expression.operator == "globally":
                positions = range(trace_length)
                operator = z3.And
            else:
                raise ValueError("unsupported temporal operator")
            terms = [
                Z3XLIRBackend._translate(
                    expression.operand,
                    variables,
                    constraints,
                    trace_length=trace_length,
                    index=position,
                    bound=bound,
                )
                for position in positions
            ]
            return operator(*terms) if terms else z3.BoolVal(expression.operator == "globally")
        if isinstance(expression, Unary):
            operand = Z3XLIRBackend._translate(
                expression.operand,
                variables,
                constraints,
                trace_length=trace_length,
                index=index,
                bound=bound,
            )
            if expression.operator == "not":
                return z3.Not(operand)
            if expression.operator == "neg":
                if expression.value_type is not ValueType.INT256:
                    raise ValueError("neg requires int256")
                constraints.append(z3.BVSNegNoOverflow(operand))
                return -operand
            if expression.operator == "bitnot":
                if expression.value_type not in {ValueType.UINT256, ValueType.INT256}:
                    raise ValueError("bitnot requires an integer")
                return ~operand
            raise ValueError("unsupported unary operator")
        if isinstance(expression, Binary):
            left = Z3XLIRBackend._translate(
                expression.left,
                variables,
                constraints,
                trace_length=trace_length,
                index=index,
                bound=bound,
            )
            right = Z3XLIRBackend._translate(
                expression.right,
                variables,
                constraints,
                trace_length=trace_length,
                index=index,
                bound=bound,
            )
            if expression.operator == "and":
                return z3.And(left, right)
            if expression.operator == "or":
                return z3.Or(left, right)
            if expression.operator == "implies":
                return z3.Implies(left, right)
            if expression.operator == "eq":
                return left == right
            if expression.operator == "neq":
                return z3.Distinct(left, right)
            if expression.operator == "ge":
                return left >= right if expression.left.value_type is ValueType.INT256 else z3.UGE(left, right)
            if expression.operator == "le":
                return left <= right if expression.left.value_type is ValueType.INT256 else z3.ULE(left, right)
            if expression.operator == "gt":
                return left > right if expression.left.value_type is ValueType.INT256 else z3.UGT(left, right)
            if expression.operator == "lt":
                return left < right if expression.left.value_type is ValueType.INT256 else z3.ULT(left, right)
            if expression.operator == "add":
                if expression.value_type is ValueType.INT256:
                    constraints.extend((z3.BVAddNoOverflow(left, right, True), z3.BVAddNoUnderflow(left, right)))
                else:
                    constraints.append(z3.BVAddNoOverflow(left, right, False))
                return left + right
            if expression.operator == "sub":
                if expression.value_type is ValueType.INT256:
                    constraints.extend((z3.BVSubNoUnderflow(left, right, True), z3.BVSubNoOverflow(left, right)))
                else:
                    constraints.append(z3.BVSubNoUnderflow(left, right, False))
                return left - right
            if expression.operator == "mul":
                if expression.value_type is ValueType.INT256:
                    constraints.extend((z3.BVMulNoOverflow(left, right, True), z3.BVMulNoUnderflow(left, right)))
                else:
                    constraints.append(z3.BVMulNoOverflow(left, right, False))
                return left * right
            if expression.operator == "div":
                constraints.append(right != z3.BitVecVal(0, right.size()))
                if expression.value_type is ValueType.INT256:
                    constraints.append(z3.BVSDivNoOverflow(left, right))
                    return left / right
                return z3.UDiv(left, right)
            if expression.operator == "mod":
                constraints.append(right != z3.BitVecVal(0, right.size()))
                return z3.SRem(left, right) if expression.value_type is ValueType.INT256 else z3.URem(left, right)
            if expression.operator == "band":
                return left & right
            if expression.operator == "bor":
                return left | right
            if expression.operator == "bxor":
                return left ^ right
            if expression.operator == "shl":
                return left << right
            if expression.operator == "shr":
                return z3.LShR(left, right)
            if expression.operator == "sar":
                return left >> right
            raise ValueError("unsupported binary operator")
        raise ValueError(f"unsupported expression object {type(expression).__name__}")

    @staticmethod
    def _model_values(model: z3.ModelRef, variables: dict[str, tuple[z3.ExprRef, ValueType]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, (variable, value_type) in sorted(variables.items()):
            value = model.eval(variable, model_completion=True)
            if value_type is ValueType.BOOL:
                result[key] = z3.is_true(value)
            else:
                number = value.as_long()
                if value_type is ValueType.INT256:
                    result[key] = value.as_signed_long()
                else:
                    width = 40 if value_type is ValueType.ADDRESS else 64
                    result[key] = f"0x{number:0{width}x}"
        return result

    @staticmethod
    def _solver_name() -> str:
        return f"z3-{z3.get_version_string()}"

    def _result(
        self,
        status: SearchStatus,
        complete: bool,
        model: dict[str, object],
        reason: str | None,
        started: float,
        query_hash: str,
    ) -> SMTResult:
        return SMTResult(status, complete, model, reason, max(0.0, time.monotonic() - started), self._solver_name(), query_hash)
