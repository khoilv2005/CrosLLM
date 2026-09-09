"""Parse and ground a deliberately small JSON XLIR proposal language."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..artifacts import ArtifactSymbol
from ..contracts.canonical import sha256_hex
from .model import (
    Binary,
    BoundRef,
    Expression,
    Invariant,
    Literal,
    Quantifier,
    SymbolRef,
    Temporal,
    Unary,
    ValueType,
)
from .primitives import PrimitiveExpansionError, expand_primitive


@dataclass(frozen=True, slots=True)
class Diagnostic:
    path: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class CompilationResult:
    invariant: Invariant | None
    abstained: bool
    diagnostics: tuple[Diagnostic, ...]

    @property
    def ok(self) -> bool:
        return self.invariant is not None and not self.diagnostics


class _CompileFailure(Exception):
    def __init__(self, path: str, code: str, message: str) -> None:
        super().__init__(message)
        self.diagnostic = Diagnostic(path, code, message)


class XLIRCompiler:
    """Compile untrusted proposal JSON against the public artifact symbol table.

    This class does not assess whether a proposed invariant is a warranted
    security property. It only establishes syntax, types, state annotation and
    grounding, leaving legitimacy/vacuity/search to later protocol stages.
    """

    _unary = {"not", "neg", "bitnot"}
    _boolean_binary = {"and", "or", "implies"}
    _comparison_binary = {"eq", "neq"}
    _ordering_binary = {"ge", "le", "gt", "lt"}
    _arithmetic_binary = {"add", "sub", "mul", "div", "mod"}
    _bitwise_binary = {"band", "bor", "bxor"}
    _shift_binary = {"shl", "shr", "sar"}
    _integer_types = {ValueType.UINT256, ValueType.INT256}

    def __init__(self, symbols: Mapping[str, ArtifactSymbol], maximum_ast_nodes: int = 256) -> None:
        if maximum_ast_nodes < 1:
            raise ValueError("maximum_ast_nodes must be positive")
        self._symbols = dict(symbols)
        self._maximum_ast_nodes = maximum_ast_nodes
        self._nodes = 0
        self._bound_variables: dict[str, ValueType] = {}

    @classmethod
    def from_symbols(
        cls, symbols: list[ArtifactSymbol], maximum_ast_nodes: int = 256
    ) -> "XLIRCompiler":
        ids = [symbol.symbol_id for symbol in symbols]
        if len(ids) != len(set(ids)):
            raise ValueError("symbol table contains duplicate symbol_id values")
        return cls({symbol.symbol_id: symbol for symbol in symbols}, maximum_ast_nodes)

    def compile(self, payload: object) -> CompilationResult:
        self._nodes = 0
        self._bound_variables = {}
        if not isinstance(payload, dict):
            return self._failure("$", "invalid_payload", "proposal payload must be an object")
        if payload.get("abstain") is True:
            allowed = {"abstain", "reason"}
            extras = set(payload) - allowed
            if extras:
                return self._failure("$", "invalid_abstain", "abstain payload has unsupported fields")
            if not isinstance(payload.get("reason"), str) or not payload["reason"].strip():
                return self._failure("$.reason", "missing_reason", "abstain requires a non-empty reason")
            return CompilationResult(None, True, ())
        try:
            if payload.get("kind") != "invariant":
                raise _CompileFailure("$.kind", "invalid_kind", "proposal kind must be invariant")
            extras = set(payload) - {"kind", "invariant_id", "body"}
            if extras:
                raise _CompileFailure(
                    "$",
                    "unsupported_fields",
                    f"invariant payload has unsupported fields: {', '.join(sorted(extras))}",
                )
            invariant_id = payload.get("invariant_id")
            if invariant_id is not None and (not isinstance(invariant_id, str) or not invariant_id):
                raise _CompileFailure("$.invariant_id", "invalid_identifier", "invariant_id must be a non-empty string")
            body = self._expression(payload.get("body"), "$.body")
            if body.value_type is not ValueType.BOOL:
                raise _CompileFailure("$.body", "non_boolean_root", "invariant body must have type bool")
            canonical_body = body.as_dict()
            invariant = Invariant(
                invariant_id=invariant_id,
                body=body,
                canonical_hash=sha256_hex(canonical_body),
                node_count=self._nodes,
            )
            return CompilationResult(invariant, False, ())
        except _CompileFailure as error:
            return self._failure_from(error)
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            # JSON from a provider is untrusted.  A malformed value must stay
            # a candidate-level diagnostic rather than escaping into the
            # campaign worker and being mistaken for a provider outage.
            return self._failure(
                "$",
                "malformed_payload",
                f"proposal contains an invalid JSON value: {error}",
            )

    def _expression(self, raw: object, path: str) -> Expression:
        self._nodes += 1
        if self._nodes > self._maximum_ast_nodes:
            raise _CompileFailure(path, "ast_limit", f"AST exceeds {self._maximum_ast_nodes} nodes")
        if not isinstance(raw, dict):
            raise _CompileFailure(path, "invalid_expression", "expression must be an object")
        kind = raw.get("kind")
        allowed_fields = {
            "symbol": {"kind", "symbol_id", "state"},
            "bound": {"kind", "variable", "type"},
            "literal": {"kind", "type", "value"},
            "unary": {"kind", "operator", "operand"},
            "binary": {"kind", "operator", "left", "right"},
            "quantifier": {"kind", "operator", "variable", "variable_type", "domain", "body"},
            "temporal": {"kind", "operator", "operand", "horizon"},
            "primitive": {"kind", "primitive_id", "arguments"},
        }.get(kind)
        if allowed_fields is not None:
            extras = set(raw) - allowed_fields
            if extras:
                raise _CompileFailure(
                    path,
                    "unsupported_fields",
                    f"{kind} expression has unsupported fields: {', '.join(sorted(extras))}",
                )
        if kind == "symbol":
            return self._symbol(raw, path)
        if kind == "bound":
            return self._bound_ref(raw, path)
        if kind == "literal":
            return self._literal(raw, path)
        if kind == "unary":
            return self._unary_expression(raw, path)
        if kind == "binary":
            return self._binary_expression(raw, path)
        if kind == "quantifier":
            return self._quantifier(raw, path)
        if kind == "temporal":
            return self._temporal(raw, path)
        if kind == "primitive":
            try:
                expanded = expand_primitive(raw)
            except PrimitiveExpansionError as error:
                raise _CompileFailure(path, "invalid_primitive", str(error)) from error
            return self._expression(expanded, f"{path}.expanded")
        raise _CompileFailure(f"{path}.kind", "invalid_expression_kind", "unknown expression kind")

    def _symbol(self, raw: dict[str, Any], path: str) -> SymbolRef:
        symbol_id = raw.get("symbol_id")
        if not isinstance(symbol_id, str) or not symbol_id:
            raise _CompileFailure(f"{path}.symbol_id", "invalid_symbol", "symbol_id must be a non-empty string")
        symbol = self._symbols.get(symbol_id)
        if symbol is None:
            raise _CompileFailure(f"{path}.symbol_id", "unresolved_symbol", f"unknown symbol_id {symbol_id!r}")
        state = raw.get("state")
        if state not in {"pre", "post"}:
            raise _CompileFailure(f"{path}.state", "invalid_state", "symbol state must be pre or post")
        try:
            value_type = ValueType(symbol.type)
        except ValueError as error:
            raise _CompileFailure(f"{path}.symbol_id", "unsupported_symbol_type", f"unsupported symbol type {symbol.type!r}") from error
        return SymbolRef(symbol_id, value_type, symbol.domain, state)

    def _bound_ref(self, raw: dict[str, Any], path: str) -> BoundRef:
        variable = raw.get("variable")
        if not isinstance(variable, str) or not variable:
            raise _CompileFailure(f"{path}.variable", "invalid_bound_variable", "bound variable must be a non-empty string")
        declared = self._bound_variables.get(variable)
        if declared is None:
            raise _CompileFailure(f"{path}.variable", "unresolved_bound_variable", f"unknown bound variable {variable!r}")
        try:
            value_type = ValueType(raw.get("type"))
        except ValueError as error:
            raise _CompileFailure(f"{path}.type", "invalid_bound_type", "bound reference type is unsupported") from error
        if value_type is not declared:
            raise _CompileFailure(f"{path}.type", "type_mismatch", "bound reference type does not match its quantifier")
        return BoundRef(variable, value_type)

    @staticmethod
    def _literal(raw: dict[str, Any], path: str) -> Literal:
        try:
            value_type = ValueType(raw.get("type"))
        except ValueError as error:
            raise _CompileFailure(f"{path}.type", "invalid_literal_type", "literal type is unsupported") from error
        value = raw.get("value")
        valid = (
            (value_type is ValueType.BOOL and isinstance(value, bool))
            or (value_type is ValueType.UINT256 and isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2**256)
            or (value_type is ValueType.INT256 and isinstance(value, int) and not isinstance(value, bool) and -(2**255) <= value < 2**255)
            or (value_type is ValueType.ADDRESS and _is_hex_literal(value, 42))
            or (value_type is ValueType.BYTES32 and _is_hex_literal(value, 66))
        )
        if not valid:
            raise _CompileFailure(path, "invalid_literal", f"value is invalid for {value_type}")
        return Literal(value, value_type)

    def _unary_expression(self, raw: dict[str, Any], path: str) -> Unary:
        operator = raw.get("operator")
        if operator not in self._unary:
            raise _CompileFailure(f"{path}.operator", "invalid_unary_operator", "unsupported unary operator")
        operand = self._expression(raw.get("operand"), f"{path}.operand")
        if operator == "not":
            if operand.value_type is not ValueType.BOOL:
                raise _CompileFailure(path, "type_mismatch", "not requires a bool operand")
            return Unary(operator, operand, ValueType.BOOL)
        if operand.value_type not in self._integer_types:
            raise _CompileFailure(path, "type_mismatch", f"{operator} requires an integer operand")
        if operator == "neg" and operand.value_type is not ValueType.INT256:
            raise _CompileFailure(path, "type_mismatch", "neg requires an int256 operand")
        return Unary(operator, operand, operand.value_type)

    def _binary_expression(self, raw: dict[str, Any], path: str) -> Binary:
        operator = raw.get("operator")
        left = self._expression(raw.get("left"), f"{path}.left")
        right = self._expression(raw.get("right"), f"{path}.right")
        if operator in self._boolean_binary:
            if left.value_type is not ValueType.BOOL or right.value_type is not ValueType.BOOL:
                raise _CompileFailure(path, "type_mismatch", f"{operator} requires bool operands")
            return Binary(operator, left, right, ValueType.BOOL)
        if operator in self._comparison_binary:
            if left.value_type is not right.value_type:
                raise _CompileFailure(path, "type_mismatch", f"{operator} requires equal operand types")
            return Binary(operator, left, right, ValueType.BOOL)
        if operator in self._ordering_binary:
            if left.value_type not in {ValueType.UINT256, ValueType.INT256} or right.value_type is not left.value_type:
                raise _CompileFailure(path, "type_mismatch", f"{operator} requires equal integer operands")
            return Binary(operator, left, right, ValueType.BOOL)
        if operator in self._arithmetic_binary:
            if left.value_type not in self._integer_types or right.value_type is not left.value_type:
                raise _CompileFailure(path, "type_mismatch", f"{operator} requires equal integer operands")
            return Binary(operator, left, right, left.value_type)
        if operator in self._bitwise_binary:
            if left.value_type not in self._integer_types or right.value_type is not left.value_type:
                raise _CompileFailure(path, "type_mismatch", f"{operator} requires equal integer operands")
            return Binary(operator, left, right, left.value_type)
        if operator in self._shift_binary:
            if operator == "sar":
                valid_left = left.value_type is ValueType.INT256
            else:
                valid_left = left.value_type in self._integer_types
            if not valid_left or right.value_type is not ValueType.UINT256:
                raise _CompileFailure(
                    path,
                    "type_mismatch",
                    f"{operator} requires an integer left operand and uint256 shift amount",
                )
            return Binary(operator, left, right, left.value_type)
        raise _CompileFailure(f"{path}.operator", "invalid_binary_operator", "unsupported binary operator")

    def _quantifier(self, raw: dict[str, Any], path: str) -> Quantifier:
        operator = raw.get("operator")
        if operator not in {"forall", "exists"}:
            raise _CompileFailure(f"{path}.operator", "invalid_quantifier_operator", "quantifier must be forall or exists")
        variable = raw.get("variable")
        if not isinstance(variable, str) or not variable or variable in self._bound_variables:
            raise _CompileFailure(f"{path}.variable", "invalid_bound_variable", "quantifier variable must be unique and non-empty")
        try:
            value_type = ValueType(raw.get("variable_type"))
        except ValueError as error:
            raise _CompileFailure(f"{path}.variable_type", "invalid_bound_type", "quantifier variable type is unsupported") from error
        raw_domain = raw.get("domain")
        if not isinstance(raw_domain, list) or any(not isinstance(item, dict) for item in raw_domain):
            raise _CompileFailure(f"{path}.domain", "invalid_quantifier_domain", "quantifier domain must be an explicit literal array")
        domain: list[Literal] = []
        for index, item in enumerate(raw_domain):
            self._nodes += 1
            if self._nodes > self._maximum_ast_nodes:
                raise _CompileFailure(
                    f"{path}.domain[{index}]", "ast_limit", f"AST exceeds {self._maximum_ast_nodes} nodes"
                )
            literal = self._literal(item, f"{path}.domain[{index}]")
            if literal.value_type is not value_type:
                raise _CompileFailure(f"{path}.domain[{index}]", "type_mismatch", "quantifier domain literal has the wrong type")
            domain.append(literal)
        previous = self._bound_variables.get(variable)
        self._bound_variables[variable] = value_type
        try:
            body = self._expression(raw.get("body"), f"{path}.body")
        finally:
            if previous is None:
                self._bound_variables.pop(variable, None)
            else:
                self._bound_variables[variable] = previous
        if body.value_type is not ValueType.BOOL:
            raise _CompileFailure(f"{path}.body", "non_boolean_quantifier_body", "quantifier body must have type bool")
        return Quantifier(operator, variable, value_type, tuple(domain), body)

    def _temporal(self, raw: dict[str, Any], path: str) -> Temporal:
        operator = raw.get("operator")
        if operator not in {"once", "globally"}:
            raise _CompileFailure(f"{path}.operator", "invalid_temporal_operator", "temporal operator must be once or globally")
        horizon = raw.get("horizon")
        if operator == "once":
            if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 0:
                raise _CompileFailure(f"{path}.horizon", "invalid_temporal_horizon", "once requires a non-negative integer horizon")
        elif horizon is not None:
            raise _CompileFailure(f"{path}.horizon", "unexpected_temporal_horizon", "globally does not accept a horizon")
        operand = self._expression(raw.get("operand"), f"{path}.operand")
        if operand.value_type is not ValueType.BOOL:
            raise _CompileFailure(f"{path}.operand", "type_mismatch", "temporal operand must have type bool")
        return Temporal(operator, operand, horizon)

    @staticmethod
    def _failure(path: str, code: str, message: str) -> CompilationResult:
        return CompilationResult(None, False, (Diagnostic(path, code, message),))

    @staticmethod
    def _failure_from(error: _CompileFailure) -> CompilationResult:
        return CompilationResult(None, False, (error.diagnostic,))


def _is_hex_literal(value: object, length: int) -> bool:
    if not isinstance(value, str) or len(value) != length or not value.startswith("0x"):
        return False
    try:
        int(value[2:], 16)
    except ValueError:
        return False
    return True
