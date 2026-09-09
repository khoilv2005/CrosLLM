"""Deterministic, solver-neutral lowering for the supported XLIR core.

The output uses SMT-LIB-like terms and explicit sorts, but this module does not
invoke a solver. Keeping lowering pure makes it possible to compare a future
SMT backend with the concrete evaluator on the same compiled invariant.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts.canonical import sha256_hex
from .model import Binary, BoundRef, Expression, Invariant, Literal, Quantifier, SymbolRef, Temporal, Unary, ValueType


@dataclass(frozen=True, slots=True)
class LoweringDiagnostic:
    path: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class SolverNode:
    node_id: str
    xlir_path: str
    sort: str
    term: str


@dataclass(frozen=True, slots=True)
class SolverIR:
    invariant_id: str | None
    root: SolverNode
    nodes: tuple[SolverNode, ...]
    source_map: dict[str, str]
    symbol_names: dict[str, str]
    invariant_hash: str
    trace_length: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "invariant_id": self.invariant_id,
            "root": self.root.term,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "xlir_path": node.xlir_path,
                    "sort": node.sort,
                    "term": node.term,
                }
                for node in self.nodes
            ],
            "source_map": dict(self.source_map),
            "symbol_names": dict(self.symbol_names),
            "invariant_hash": self.invariant_hash,
            "trace_length": self.trace_length,
        }


@dataclass(frozen=True, slots=True)
class LoweringResult:
    ir: SolverIR | None
    diagnostics: tuple[LoweringDiagnostic, ...]

    @property
    def ok(self) -> bool:
        return self.ir is not None and not self.diagnostics


class XLIRLowerer:
    """Lower a compiled invariant without making solver-specific assumptions."""

    _sorts = {
        ValueType.BOOL: "Bool",
        ValueType.UINT256: "(_ BitVec 256)",
        ValueType.INT256: "(_ BitVec 256)",
        ValueType.ADDRESS: "(_ BitVec 160)",
        ValueType.BYTES32: "(_ BitVec 256)",
    }
    _binary = {
        "and": "and",
        "or": "or",
        "implies": "=>",
        "eq": "=",
        "neq": "distinct",
        "ge": "bvuge",
        "le": "bvule",
        "gt": "bvugt",
        "lt": "bvult",
        "add": "bvadd",
        "sub": "bvsub",
        "mul": "bvmul",
        "band": "bvand",
        "bor": "bvor",
        "bxor": "bvxor",
        "shl": "bvshl",
        "shr": "bvlshr",
        "sar": "bvashr",
    }

    def lower(self, invariant: Invariant, *, trace_length: int | None = None) -> LoweringResult:
        nodes: list[SolverNode] = []
        symbol_names: dict[str, str] = {}
        if trace_length is not None and (
            not isinstance(trace_length, int) or isinstance(trace_length, bool) or trace_length <= 0
        ):
            return LoweringResult(
                None,
                (LoweringDiagnostic("$", "invalid_trace_length", "trace_length must be a positive integer"),),
            )

        try:
            root = self._lower_expression(
                invariant.body,
                "$.body",
                nodes,
                symbol_names,
                {},
                0,
                trace_length,
            )
            if root.sort != "Bool":
                return LoweringResult(
                    None,
                    (LoweringDiagnostic("$.body", "non_boolean_root", "solver root must have Bool sort"),),
                )
        except ValueError as error:
            path, message = str(error).split("|", 1)
            return LoweringResult(None, (LoweringDiagnostic(path, "unsupported_node", message),))

        return LoweringResult(
            SolverIR(
                invariant_id=invariant.invariant_id,
                root=root,
                nodes=tuple(nodes),
                source_map={node.node_id: node.xlir_path for node in nodes},
                symbol_names=dict(symbol_names),
                invariant_hash=sha256_hex(
                    {
                        "invariant_hash": invariant.canonical_hash,
                        "root": root.term,
                        "trace_length": trace_length,
                    }
                ),
                trace_length=trace_length,
            ),
            (),
        )

    def _lower_expression(
        self,
        expression: Expression,
        path: str,
        nodes: list[SolverNode],
        symbol_names: dict[str, str],
        bound: dict[str, Literal],
        index: int,
        trace_length: int | None,
    ) -> SolverNode:
        if isinstance(expression, SymbolRef):
            binding_key = f"{expression.symbol_id}|{expression.state}|{expression.domain}"
            if trace_length is not None:
                binding_key = f"{binding_key}|trace_index={index}"
            name = symbol_names.setdefault(
                binding_key,
                f"s_{sha256_hex(binding_key)[:16]}",
            )
            node = SolverNode(f"n{len(nodes)}", path, self._sorts[expression.value_type], name)
        elif isinstance(expression, BoundRef):
            literal = bound.get(expression.variable)
            if literal is None:
                raise ValueError(f"{path}|unresolved bound variable")
            node = SolverNode(
                f"n{len(nodes)}",
                path,
                self._sorts[literal.value_type],
                self._literal(literal),
            )
        elif isinstance(expression, Literal):
            node = SolverNode(
                f"n{len(nodes)}", path, self._sorts[expression.value_type], self._literal(expression)
            )
        elif isinstance(expression, Unary):
            operand = self._lower_expression(
                expression.operand, f"{path}.operand", nodes, symbol_names, bound, index, trace_length
            )
            if expression.operator == "not":
                if operand.sort != "Bool":
                    raise ValueError(f"{path}|not requires Bool sort")
                term = f"(not {operand.term})"
            elif expression.operator == "neg":
                if expression.value_type is not ValueType.INT256:
                    raise ValueError(f"{path}|neg requires int256")
                term = f"(bvneg {operand.term})"
            elif expression.operator == "bitnot":
                if expression.value_type not in {ValueType.UINT256, ValueType.INT256}:
                    raise ValueError(f"{path}|bitnot requires an integer")
                term = f"(bvnot {operand.term})"
            else:
                raise ValueError(f"{path}|unsupported unary expression")
            node = SolverNode(f"n{len(nodes)}", path, self._sorts[expression.value_type], term)
        elif isinstance(expression, Binary):
            left = self._lower_expression(
                expression.left, f"{path}.left", nodes, symbol_names, bound, index, trace_length
            )
            right = self._lower_expression(
                expression.right, f"{path}.right", nodes, symbol_names, bound, index, trace_length
            )
            operator = self._binary.get(expression.operator)
            if operator is None:
                raise ValueError(f"{path}.operator|unsupported binary operator")
            if expression.left.value_type is ValueType.INT256 and expression.operator in {"ge", "le", "gt", "lt"}:
                operator = {"ge": "bvsge", "le": "bvsle", "gt": "bvsgt", "lt": "bvslt"}[expression.operator]
            if expression.operator == "div":
                operator = "bvsdiv" if expression.left.value_type is ValueType.INT256 else "bvudiv"
            if expression.operator == "mod":
                operator = "bvsrem" if expression.left.value_type is ValueType.INT256 else "bvurem"
            if expression.operator == "neq":
                term = f"(distinct {left.term} {right.term})"
            else:
                term = f"({operator} {left.term} {right.term})"
            node = SolverNode(
                f"n{len(nodes)}",
                path,
                self._sorts[expression.value_type],
                term,
            )
        elif isinstance(expression, Quantifier):
            terms: list[str] = []
            for domain_index, literal in enumerate(expression.domain):
                quantified = dict(bound)
                quantified[expression.variable] = literal
                body = self._lower_expression(
                    expression.body,
                    f"{path}.domain[{domain_index}].body",
                    nodes,
                    symbol_names,
                    quantified,
                    index,
                    trace_length,
                )
                if body.sort != "Bool":
                    raise ValueError(f"{path}|quantifier body is not Bool")
                terms.append(body.term)
            operator = "and" if expression.operator == "forall" else "or" if expression.operator == "exists" else None
            if operator is None:
                raise ValueError(f"{path}|unsupported quantifier operator")
            identity = "true" if expression.operator == "forall" else "false"
            term = identity if not terms else f"({operator} {' '.join(terms)})"
            node = SolverNode(f"n{len(nodes)}", path, "Bool", term)
        elif isinstance(expression, Temporal):
            if trace_length is None:
                raise ValueError(f"{path}|temporal lowering requires trace_length")
            if expression.operator == "once":
                assert expression.horizon is not None
                positions = range(max(0, index - expression.horizon), index + 1)
                operator = "or"
            elif expression.operator == "globally":
                positions = range(trace_length)
                operator = "and"
            else:
                raise ValueError(f"{path}|unsupported temporal operator")
            terms = [
                self._lower_expression(
                    expression.operand,
                    f"{path}.index[{position}]",
                    nodes,
                    symbol_names,
                    bound,
                    position,
                    trace_length,
                ).term
                for position in positions
            ]
            node = SolverNode(
                f"n{len(nodes)}",
                path,
                "Bool",
                f"({operator} {' '.join(terms)})" if len(terms) > 1 else terms[0],
            )
        else:
            raise ValueError(f"{path}|unsupported expression object")
        nodes.append(node)
        return node

    @staticmethod
    def _literal(literal: Literal) -> str:
        if literal.value_type is ValueType.BOOL:
            return "true" if literal.value else "false"
        if literal.value_type is ValueType.UINT256:
            return f"(_ bv{literal.value} 256)"
        if literal.value_type is ValueType.INT256:
            value = int(literal.value)
            if value < 0:
                value %= 2**256
            return f"(_ bv{value} 256)"
        if literal.value_type is ValueType.ADDRESS:
            return f"(_ bv{int(literal.value[2:], 16)} 160)"
        if literal.value_type is ValueType.BYTES32:
            return f"(_ bv{int(literal.value[2:], 16)} 256)"
        raise ValueError("$|unsupported literal type")
