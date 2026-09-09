"""Independent concrete property-evaluation boundary for replay observations.

The evaluator consumes an observation already produced by a replay adapter and
uses the concrete XLIR evaluator directly.  It never calls the SMT lowerer or
infers security relevance; missing/invalid bindings remain ``UNKNOWN``.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping

from ..contracts.canonical import sha256_hex
from ..contracts.records import ReplayStatus
from ..xlir.evaluator import EvaluationError, StateBindings, evaluate_invariant
from ..xlir.model import Invariant


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class SourceObservation:
    """Normalized state observation emitted by an independent replay adapter."""

    observation_id: str
    trace_hash: str
    bindings: StateBindings

    def __post_init__(self) -> None:
        if not self.observation_id:
            raise ValueError("observation_id is required")
        if not isinstance(self.trace_hash, str) or _HEX64.fullmatch(self.trace_hash) is None:
            raise ValueError("trace_hash must be a lowercase SHA-256 hex digest")
        if not isinstance(self.bindings, Mapping):
            raise ValueError("observation bindings must be a mapping")
        for key in self.bindings:
            if not isinstance(key, tuple) or len(key) != 3:
                raise ValueError("observation binding keys must be (symbol_id, state, domain) tuples")
            if any(not isinstance(value, str) or not value for value in key):
                raise ValueError("observation binding key fields must be non-empty strings")
            if key[1] not in {"pre", "post"}:
                raise ValueError("observation binding state must be pre or post")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "observation_id": self.observation_id,
            "trace_hash": self.trace_hash,
            "bindings": [
                {
                    "symbol_id": symbol_id,
                    "state": state,
                    "domain": domain,
                    "value": self.bindings[(symbol_id, state, domain)],
                }
                for symbol_id, state, domain in sorted(self.bindings)
            ],
        }

    @property
    def observation_hash(self) -> str:
        return sha256_hex(self.as_dict())


@dataclass(frozen=True, slots=True)
class PropertyEvaluatorSpec:
    """Hash-bound identity for the concrete evaluator and replay context."""

    evaluator_id: str
    evaluator_revision: str
    artifact_hash: str
    initialization_hash: str
    profile_hash: str
    semantic_engine: str
    support_matrix_hash: str | None = None

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value for value in (
            self.evaluator_id,
            self.evaluator_revision,
            self.semantic_engine,
        )):
            raise ValueError("property evaluator identity is incomplete")
        for name in ("artifact_hash", "initialization_hash", "profile_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
        if self.support_matrix_hash is not None and _HEX64.fullmatch(self.support_matrix_hash) is None:
            raise ValueError("support_matrix_hash must be a lowercase SHA-256 hex digest")

    @property
    def spec_hash(self) -> str:
        return sha256_hex(self.as_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "evaluator_id": self.evaluator_id,
            "evaluator_revision": self.evaluator_revision,
            "artifact_hash": self.artifact_hash,
            "initialization_hash": self.initialization_hash,
            "profile_hash": self.profile_hash,
            "semantic_engine": self.semantic_engine,
            "support_matrix_hash": self.support_matrix_hash,
        }


@dataclass(frozen=True, slots=True)
class PropertyEvaluationResult:
    """Concrete property outcome with explicit non-security boundary."""

    evaluator_spec_hash: str
    property_hash: str
    observation_hash: str
    trace_hash: str
    status: ReplayStatus
    property_holds: bool | None
    security_relevance: str = "unassessed"
    reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("evaluator_spec_hash", "property_hash", "observation_hash", "trace_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
        if self.security_relevance not in {"unassessed", "relevant", "irrelevant", "unknown"}:
            raise ValueError("invalid security_relevance")
        if self.status in {ReplayStatus.PASS, ReplayStatus.FAIL} and not isinstance(self.property_holds, bool):
            raise ValueError("pass/fail property results require property_holds")
        if self.status in {ReplayStatus.UNKNOWN, ReplayStatus.UNSUPPORTED} and self.property_holds is not None:
            raise ValueError("unknown/unsupported property results cannot claim property_holds")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "evaluator_spec_hash": self.evaluator_spec_hash,
            "property_hash": self.property_hash,
            "observation_hash": self.observation_hash,
            "trace_hash": self.trace_hash,
            "status": self.status.value,
            "property_holds": self.property_holds,
            "security_relevance": self.security_relevance,
            "reason": self.reason,
        }


class IndependentPropertyEvaluator:
    """Evaluate a compiled invariant without using SMT lowering."""

    def evaluate(
        self,
        spec: PropertyEvaluatorSpec,
        invariant: Invariant,
        observation: SourceObservation,
    ) -> PropertyEvaluationResult:
        try:
            property_hash = sha256_hex(invariant.body.as_dict())
        except (AttributeError, TypeError, ValueError) as error:
            # Keep the result schema valid even when an evaluator receives a
            # malformed object instead of a compiler-produced Invariant.
            property_hash = sha256_hex({"invalid_invariant": type(invariant).__name__})
            return PropertyEvaluationResult(
                evaluator_spec_hash=spec.spec_hash,
                property_hash=property_hash,
                observation_hash=observation.observation_hash,
                trace_hash=observation.trace_hash,
                status=ReplayStatus.UNKNOWN,
                property_holds=None,
                reason=f"invalid_invariant:{type(error).__name__}:{error}",
            )
        if invariant.canonical_hash != property_hash:
            return PropertyEvaluationResult(
                evaluator_spec_hash=spec.spec_hash,
                property_hash=property_hash,
                observation_hash=observation.observation_hash,
                trace_hash=observation.trace_hash,
                status=ReplayStatus.UNKNOWN,
                property_holds=None,
                reason="invariant_canonical_hash_mismatch",
            )
        try:
            holds = evaluate_invariant(invariant, observation.bindings)
        except EvaluationError as error:
            return PropertyEvaluationResult(
                evaluator_spec_hash=spec.spec_hash,
                property_hash=property_hash,
                observation_hash=observation.observation_hash,
                trace_hash=observation.trace_hash,
                status=ReplayStatus.UNKNOWN,
                property_holds=None,
                reason=f"observation_binding_error:{error}",
            )
        return PropertyEvaluationResult(
            evaluator_spec_hash=spec.spec_hash,
            property_hash=property_hash,
            observation_hash=observation.observation_hash,
            trace_hash=observation.trace_hash,
            status=ReplayStatus.PASS if holds else ReplayStatus.FAIL,
            property_holds=holds,
        )


__all__ = [
    "IndependentPropertyEvaluator",
    "PropertyEvaluationResult",
    "PropertyEvaluatorSpec",
    "SourceObservation",
]
