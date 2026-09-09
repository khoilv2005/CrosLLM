"""Pure evaluator for a grounded XLIR invariant over explicit state bindings.

The evaluator is intentionally small and deterministic. It is useful for tiny
fixture checks and for testing a future SMT lowering, but it is not an EVM
interpreter and it does not establish that a property is security-relevant.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .model import Binary, BoundRef, Expression, Invariant, Literal, Quantifier, SymbolRef, Temporal, Unary, ValueType


class EvaluationError(ValueError):
    """The supplied concrete binding cannot be evaluated under XLIR types."""


StateBindings = Mapping[tuple[str, str, str], object]
TraceBindings = Sequence[StateBindings]

_UINT256_WIDTH = 256
_UINT256_LIMIT = 2**_UINT256_WIDTH
_INT256_MIN = -(2**(_UINT256_WIDTH - 1))
_INT256_MAX = 2**(_UINT256_WIDTH - 1) - 1


def evaluate_invariant(invariant: Invariant, bindings: StateBindings) -> bool:
    """Evaluate an invariant using ``(symbol_id, state, domain)`` bindings.

    Requiring the complete key prevents accidentally using a post-state value
    for a pre-state symbol or crossing source/destination domains. Missing
    values and arithmetic underflow are errors, not a false property result.
    """

    value = evaluate_expression(invariant.body, bindings)
    if not isinstance(value, bool):
        raise EvaluationError("invariant body did not evaluate to bool")
    return value


def evaluate_trace(invariant: Invariant, trace: TraceBindings) -> bool:
    """Evaluate an invariant at trace index zero under finite-trace semantics."""
    if not trace:
        raise EvaluationError("finite trace must contain at least one observation")
    value = evaluate_expression(invariant.body, trace[0], trace=trace, index=0)
    if not isinstance(value, bool):
        raise EvaluationError("invariant body did not evaluate to bool")
    return value


def evaluate_expression(
    expression: Expression,
    bindings: StateBindings,
    *,
    trace: TraceBindings | None = None,
    index: int = 0,
) -> Any:
    """Evaluate one typed expression, optionally with finite trace context."""
    if index < 0 or trace is not None and index >= len(trace):
        raise EvaluationError("trace index is out of bounds")
    return _evaluate(expression, bindings, {}, trace, index)


def _evaluate(
    expression: Expression,
    bindings: StateBindings,
    bound: Mapping[str, object],
    trace: TraceBindings | None,
    index: int,
) -> Any:
    if isinstance(expression, SymbolRef):
        key = (expression.symbol_id, expression.state, expression.domain)
        if key not in bindings:
            raise EvaluationError(f"missing binding for {key!r}")
        value = bindings[key]
        _validate_value(value, expression.value_type, f"binding {key!r}")
        return value
    if isinstance(expression, BoundRef):
        if expression.variable not in bound:
            raise EvaluationError(f"missing bound value for {expression.variable!r}")
        value = bound[expression.variable]
        _validate_value(value, expression.value_type, f"bound value {expression.variable!r}")
        return value
    if isinstance(expression, Literal):
        _validate_value(expression.value, expression.value_type, "literal")
        return expression.value
    if isinstance(expression, Quantifier):
        values = [
            _evaluate(item, bindings, bound, trace, index)
            for item in expression.domain
        ]
        results = (
            _evaluate(expression.body, bindings, {**bound, expression.variable: value}, trace, index)
            for value in values
        )
        if expression.operator == "forall":
            return all(results)
        if expression.operator == "exists":
            return any(results)
        raise EvaluationError(f"unsupported quantifier operator {expression.operator!r}")
    if isinstance(expression, Temporal):
        if trace is None:
            raise EvaluationError("temporal expression requires finite trace context")
        if expression.operator == "once":
            assert expression.horizon is not None
            positions = range(max(0, index - expression.horizon), index + 1)
            return any(
                _evaluate(expression.operand, trace[position], bound, trace, position)
                for position in positions
            )
        if expression.operator == "globally":
            return all(
                _evaluate(expression.operand, trace[position], bound, trace, position)
                for position in range(len(trace))
            )
        raise EvaluationError(f"unsupported temporal operator {expression.operator!r}")
    if isinstance(expression, Unary):
        operand = _evaluate(expression.operand, bindings, bound, trace, index)
        if expression.operator == "not":
            return not operand
        if expression.operator == "neg":
            if expression.value_type is not ValueType.INT256:
                raise EvaluationError("neg requires int256")
            if operand == _INT256_MIN:
                raise EvaluationError("int256 negation overflow")
            return -operand
        if expression.operator == "bitnot":
            if expression.value_type not in {ValueType.UINT256, ValueType.INT256}:
                raise EvaluationError("bitnot requires an integer")
            return _normalize_integer(~operand, expression.value_type)
        raise EvaluationError(f"unsupported unary operator {expression.operator!r}")
    if isinstance(expression, Binary):
        left = _evaluate(expression.left, bindings, bound, trace, index)
        # Preserve Boolean short-circuit semantics for the logical operators.
        if expression.operator == "and":
            return left and _evaluate(expression.right, bindings, bound, trace, index)
        if expression.operator == "or":
            return left or _evaluate(expression.right, bindings, bound, trace, index)
        if expression.operator == "implies":
            return (not left) or _evaluate(expression.right, bindings, bound, trace, index)
        right = _evaluate(expression.right, bindings, bound, trace, index)
        if expression.operator == "eq":
            return left == right
        if expression.operator == "neq":
            return left != right
        if expression.operator == "ge":
            return left >= right
        if expression.operator == "le":
            return left <= right
        if expression.operator == "gt":
            return left > right
        if expression.operator == "lt":
            return left < right
        if expression.operator == "add":
            result = left + right
            return _checked_integer_result(result, expression.value_type, "addition")
        if expression.operator == "sub":
            if expression.value_type is ValueType.UINT256 and left < right:
                raise EvaluationError("uint256 subtraction underflow")
            result = left - right
            return _checked_integer_result(result, expression.value_type, "subtraction")
        if expression.operator == "mul":
            return _checked_integer_result(left * right, expression.value_type, "multiplication")
        if expression.operator == "div":
            if right == 0:
                raise EvaluationError("integer division by zero")
            if expression.value_type is ValueType.INT256 and left == _INT256_MIN and right == -1:
                raise EvaluationError("int256 division overflow")
            if expression.value_type is ValueType.INT256:
                sign = -1 if (left < 0) != (right < 0) else 1
                return sign * (abs(left) // abs(right))
            return left // right
        if expression.operator == "mod":
            if right == 0:
                raise EvaluationError("integer modulo by zero")
            if expression.value_type is ValueType.INT256:
                sign = -1 if left < 0 else 1
                return sign * (abs(left) % abs(right))
            return left % right
        if expression.operator in {"band", "bor", "bxor"}:
            operation = {
                "band": lambda: left & right,
                "bor": lambda: left | right,
                "bxor": lambda: left ^ right,
            }[expression.operator]
            return _normalize_integer(operation(), expression.value_type)
        if expression.operator in {"shl", "shr", "sar"}:
            if right >= _UINT256_WIDTH:
                if expression.operator == "sar":
                    return -1 if left < 0 else 0
                return 0
            shift = int(right)
            if expression.operator == "shl":
                return _normalize_integer(left << shift, expression.value_type)
            if expression.operator == "shr":
                return _normalize_integer(left, ValueType.UINT256) >> shift
            return left >> shift
        raise EvaluationError(f"unsupported binary operator {expression.operator!r}")
    raise EvaluationError(f"unsupported expression object {type(expression).__name__}")


def _validate_value(value: object, value_type: ValueType, label: str) -> None:
    valid = (
        (value_type is ValueType.BOOL and isinstance(value, bool))
        or (
            value_type is ValueType.UINT256
            and isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value < _UINT256_LIMIT
        )
        or (
            value_type is ValueType.INT256
            and isinstance(value, int)
            and not isinstance(value, bool)
            and _INT256_MIN <= value <= _INT256_MAX
        )
        or (value_type is ValueType.ADDRESS and _hex_string(value, 42))
        or (value_type is ValueType.BYTES32 and _hex_string(value, 66))
    )
    if not valid:
        raise EvaluationError(f"{label} has invalid value for {value_type.value}")


def _hex_string(value: object, length: int) -> bool:
    if not isinstance(value, str) or len(value) != length or not value.startswith("0x"):
        return False
    try:
        int(value[2:], 16)
    except ValueError:
        return False
    return True


def _normalize_integer(value: int, value_type: ValueType) -> int:
    """Normalize a bit-vector result to the public XLIR numeric view."""
    bits = value % _UINT256_LIMIT
    if value_type is ValueType.INT256 and bits >= 2**255:
        return bits - _UINT256_LIMIT
    return bits


def _checked_integer_result(value: int, value_type: ValueType, operation: str) -> int:
    if value_type is ValueType.UINT256:
        if not 0 <= value < _UINT256_LIMIT:
            detail = "overflow" if value >= _UINT256_LIMIT else "underflow"
            raise EvaluationError(f"uint256 {operation} {detail}")
        return value
    if value_type is ValueType.INT256 and not _INT256_MIN <= value <= _INT256_MAX:
        raise EvaluationError(f"int256 {operation} overflow")
    return value
