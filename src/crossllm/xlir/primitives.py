"""Solver-neutral XLIR primitive macro expansion.

Primitives are syntax sugar over the same typed Boolean core. They do not add
state, capabilities or a security oracle; every argument must still resolve to
public grounded expressions in the compiler.
"""

from __future__ import annotations

from typing import Any


class PrimitiveExpansionError(ValueError):
    """A primitive name or argument list is not part of XLIR v1."""


_ARITY = {
    "justified_destination_effect": 2,
    "replay_exclusion": 1,
    "quorum_authorization": 1,
    "proof_binding": 2,
    "callback_noninterference": 1,
    "challenge_window": 2,
    "intent_consumption": 1,
}


def expand_primitive(raw: dict[str, Any]) -> dict[str, object]:
    """Expand a primitive call into an equivalent core Boolean expression."""
    primitive_id = raw.get("primitive_id")
    arguments = raw.get("arguments")
    if not isinstance(primitive_id, str) or primitive_id not in _ARITY:
        raise PrimitiveExpansionError("unsupported primitive_id")
    if not isinstance(arguments, list) or len(arguments) != _ARITY[primitive_id]:
        raise PrimitiveExpansionError(f"{primitive_id} requires {_ARITY[primitive_id]} arguments")
    if any(not isinstance(argument, dict) for argument in arguments):
        raise PrimitiveExpansionError("primitive arguments must be expression objects")

    if primitive_id == "justified_destination_effect":
        return _binary("implies", arguments[0], arguments[1])
    if primitive_id == "replay_exclusion":
        return _unary("not", arguments[0])
    if primitive_id == "quorum_authorization":
        return arguments[0]
    if primitive_id == "proof_binding":
        return _binary("implies", arguments[0], arguments[1])
    if primitive_id == "callback_noninterference":
        return _unary("not", arguments[0])
    if primitive_id == "challenge_window":
        return _binary("implies", arguments[0], _unary("not", arguments[1]))
    if primitive_id == "intent_consumption":
        return arguments[0]
    raise PrimitiveExpansionError("unsupported primitive_id")


def _unary(operator: str, operand: dict[str, object]) -> dict[str, object]:
    return {"kind": "unary", "operator": operator, "operand": operand}


def _binary(operator: str, left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    return {"kind": "binary", "operator": operator, "left": left, "right": right}


__all__ = ["PrimitiveExpansionError", "expand_primitive"]
