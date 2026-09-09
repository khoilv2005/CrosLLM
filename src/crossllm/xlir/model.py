"""Small typed AST for grounded, bounded CrossLLM invariants.

The model intentionally excludes solver details. A future lowering pass must
preserve this AST and attach source maps instead of reparsing raw LLM output.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ValueType(StrEnum):
    BOOL = "bool"
    UINT256 = "uint256"
    INT256 = "int256"
    ADDRESS = "address"
    BYTES32 = "bytes32"


class Expression(Protocol):
    value_type: ValueType

    def as_dict(self) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class SymbolRef:
    symbol_id: str
    value_type: ValueType
    domain: str
    state: str

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": "symbol",
            "symbol_id": self.symbol_id,
            "type": self.value_type,
            "domain": self.domain,
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class Literal:
    value: bool | int | str
    value_type: ValueType

    def as_dict(self) -> dict[str, object]:
        return {"kind": "literal", "type": self.value_type, "value": self.value}


@dataclass(frozen=True, slots=True)
class Unary:
    operator: str
    operand: Expression
    value_type: ValueType

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": "unary",
            "operator": self.operator,
            "operand": self.operand.as_dict(),
            "type": self.value_type,
        }


@dataclass(frozen=True, slots=True)
class Binary:
    operator: str
    left: Expression
    right: Expression
    value_type: ValueType

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": "binary",
            "operator": self.operator,
            "left": self.left.as_dict(),
            "right": self.right.as_dict(),
            "type": self.value_type,
        }


@dataclass(frozen=True, slots=True)
class BoundRef:
    """A reference to a variable bound by an explicit finite quantifier."""

    variable: str
    value_type: ValueType

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": "bound",
            "variable": self.variable,
            "type": self.value_type,
        }


@dataclass(frozen=True, slots=True)
class Quantifier:
    """A finite, explicitly enumerated universal or existential quantifier."""

    operator: str
    variable: str
    variable_type: ValueType
    domain: tuple[Literal, ...]
    body: Expression
    value_type: ValueType = ValueType.BOOL

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": "quantifier",
            "operator": self.operator,
            "variable": self.variable,
            "variable_type": self.variable_type,
            "domain": [item.as_dict() for item in self.domain],
            "body": self.body.as_dict(),
            "type": self.value_type,
        }


@dataclass(frozen=True, slots=True)
class Temporal:
    """A finite-trace temporal operator from the XLIR V2 core."""

    operator: str
    operand: Expression
    horizon: int | None = None
    value_type: ValueType = ValueType.BOOL

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": "temporal",
            "operator": self.operator,
            "operand": self.operand.as_dict(),
            "type": self.value_type,
        }
        if self.horizon is not None:
            payload["horizon"] = self.horizon
        return payload


@dataclass(frozen=True, slots=True)
class Invariant:
    invariant_id: str | None
    body: Expression
    canonical_hash: str
    node_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": "invariant",
            "invariant_id": self.invariant_id,
            "body": self.body.as_dict(),
            "canonical_hash": self.canonical_hash,
            "node_count": self.node_count,
        }
