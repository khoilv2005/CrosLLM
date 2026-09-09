"""Conservative structural eligibility checks for XLIR security properties.

The checker deliberately does not decide whether an invariant is a correct
security requirement.  It only verifies that a caller-supplied policy's
cross-domain and state-transition obligations are represented by grounded
symbols.  Security relevance still requires an independent property review.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .model import Binary, BoundRef, Expression, Invariant, Literal, Quantifier, SymbolRef, Temporal, Unary


class LegitimacyStatus(StrEnum):
    ELIGIBLE = "structurally_eligible"
    UNWARRANTED = "unwarranted"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LegitimacyResult:
    """Result of a structural policy check, never a security verdict."""

    status: LegitimacyStatus
    referenced_symbols: tuple[str, ...]
    referenced_domains: tuple[str, ...]
    referenced_states: tuple[str, ...]
    cross_domain_relation: bool
    transition_relevant: bool
    security_validity: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "referenced_symbols": list(self.referenced_symbols),
            "referenced_domains": list(self.referenced_domains),
            "referenced_states": list(self.referenced_states),
            "cross_domain_relation": self.cross_domain_relation,
            "transition_relevant": self.transition_relevant,
            "security_validity": self.security_validity,
            "reason": self.reason,
        }


def assess_legitimacy(
    invariant: Invariant,
    *,
    required_domains: Iterable[str] = ("source", "destination"),
    required_states: Iterable[str] = ("pre", "post"),
    allowed_symbol_ids: Iterable[str] | None = None,
) -> LegitimacyResult:
    """Check policy-visible structure without treating feasibility as validity.

    The defaults require a property to relate source and destination
    observations across a pre/post transition.  A host-specific policy may
    relax these requirements explicitly for a shared or single-domain
    property.  An ``ELIGIBLE`` result means only that the representation is
    suitable for independent security-property review.
    """
    if not isinstance(invariant, Invariant):
        raise TypeError("assess_legitimacy expects an Invariant")
    required_domain_set = frozenset(required_domains)
    required_state_set = frozenset(required_states)
    if not required_domain_set <= {"source", "destination", "shared"}:
        raise ValueError("required_domains contains an unsupported domain")
    if not required_state_set <= {"pre", "post"}:
        raise ValueError("required_states contains an unsupported state")
    allowed = None if allowed_symbol_ids is None else frozenset(allowed_symbol_ids)
    symbols: dict[str, SymbolRef] = {}
    unknown_reason: str | None = None

    def visit(expression: Expression) -> tuple[set[str], set[str]]:
        nonlocal unknown_reason
        if isinstance(expression, SymbolRef):
            if expression.domain not in {"source", "destination", "shared"}:
                unknown_reason = "unsupported_symbol_domain"
            if expression.state not in {"pre", "post"}:
                unknown_reason = "unsupported_symbol_state"
            symbols[expression.symbol_id] = expression
            return {expression.domain}, {expression.state}
        if isinstance(expression, (Literal, BoundRef)):
            return set(), set()
        if isinstance(expression, Unary):
            return visit(expression.operand)
        if isinstance(expression, Binary):
            left_domains, left_states = visit(expression.left)
            right_domains, right_states = visit(expression.right)
            return left_domains | right_domains, left_states | right_states
        if isinstance(expression, Quantifier):
            return visit(expression.body)
        if isinstance(expression, Temporal):
            return visit(expression.operand)
        unknown_reason = f"unsupported_expression:{type(expression).__name__}"
        return set(), set()

    domains, states = visit(invariant.body)
    symbol_ids = tuple(sorted(symbols))
    domain_values = tuple(sorted(domains))
    state_values = tuple(sorted(states))
    cross_domain = len(domains & {"source", "destination"}) == 2
    transition_relevant = len(states & {"pre", "post"}) == 2

    if unknown_reason is not None:
        return LegitimacyResult(
            LegitimacyStatus.UNKNOWN,
            symbol_ids,
            domain_values,
            state_values,
            cross_domain,
            transition_relevant,
            "not_assessed",
            unknown_reason,
        )
    if not symbol_ids:
        reason = "no_grounded_symbols"
    elif allowed is not None and not set(symbol_ids) <= allowed:
        reason = "symbol_outside_legitimacy_context"
    elif not required_domain_set <= domains:
        reason = "missing_required_domain"
    elif not required_state_set <= states:
        reason = "missing_required_state"
    elif required_domain_set >= {"source", "destination"} and not cross_domain:
        reason = "no_source_destination_relation"
    elif required_state_set >= {"pre", "post"} and not transition_relevant:
        reason = "not_transition_relevant"
    else:
        return LegitimacyResult(
            LegitimacyStatus.ELIGIBLE,
            symbol_ids,
            domain_values,
            state_values,
            cross_domain,
            transition_relevant,
            "not_assessed",
            "structural_policy_satisfied",
        )
    return LegitimacyResult(
        LegitimacyStatus.UNWARRANTED,
        symbol_ids,
        domain_values,
        state_values,
        cross_domain,
        transition_relevant,
        "not_assessed",
        reason,
    )


__all__ = ["LegitimacyResult", "LegitimacyStatus", "assess_legitimacy"]
