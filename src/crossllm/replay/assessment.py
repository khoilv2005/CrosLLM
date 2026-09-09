"""Explicit witness/replay assessment state machine for M05.04--M05.06."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..contracts.records import ReplayStatus


class WitnessAssessmentStatus(StrEnum):
    CONFIRMED = "confirmed"
    PENDING = "pending"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ReplayAssessment:
    """Separate replay facts from the final security-relevance conclusion."""

    witness_id: str
    model_trace_valid: bool | None
    native_replay_status: ReplayStatus
    independent_replay_status: ReplayStatus
    security_relevance: bool | None
    allowed_capabilities: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    status: WitnessAssessmentStatus
    reasons: tuple[str, ...]
    native_witness_seconds: float | None = None
    evaluator_reproduction_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.witness_id:
            raise ValueError("witness_id is required")
        for name, value in (
            ("native_witness_seconds", self.native_witness_seconds),
            ("evaluator_reproduction_seconds", self.evaluator_reproduction_seconds),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")
        if not set(self.required_capabilities).issubset(self.allowed_capabilities):
            raise ValueError("required capabilities are not allowed by the witness")

    @property
    def confirmed(self) -> bool:
        return self.status is WitnessAssessmentStatus.CONFIRMED

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "witness_id": self.witness_id,
            "model_trace_valid": self.model_trace_valid,
            "native_replay_status": self.native_replay_status.value,
            "independent_replay_status": self.independent_replay_status.value,
            "security_relevance": self.security_relevance,
            "allowed_capabilities": list(self.allowed_capabilities),
            "required_capabilities": list(self.required_capabilities),
            "status": self.status.value,
            "reasons": list(self.reasons),
            "native_witness_seconds": self.native_witness_seconds,
            "evaluator_reproduction_seconds": self.evaluator_reproduction_seconds,
        }


def assess_witness(
    *,
    witness_id: str,
    model_trace_valid: bool | None,
    native_replay_status: ReplayStatus,
    independent_replay_status: ReplayStatus,
    security_relevance: bool | None,
    allowed_capabilities: tuple[str, ...] = (),
    required_capabilities: tuple[str, ...] = (),
    native_witness_seconds: float | None = None,
    evaluator_reproduction_seconds: float | None = None,
) -> ReplayAssessment:
    """Build an assessment without collapsing unknown/unsupported into failure.

    A finding is confirmed only after every required evidence layer passes. A
    hard failure or an unallowed capability rejects the witness; missing or
    unsupported independent evidence remains pending for adjudication.
    """
    if not witness_id:
        raise ValueError("witness_id is required")
    if not isinstance(native_replay_status, ReplayStatus) or not isinstance(
        independent_replay_status, ReplayStatus
    ):
        raise ValueError("replay statuses must use ReplayStatus")
    reasons: list[str] = []
    if model_trace_valid is False:
        reasons.append("model_trace_invalid")
    elif model_trace_valid is None:
        reasons.append("model_trace_unassessed")
    if native_replay_status is ReplayStatus.FAIL:
        reasons.append("native_replay_failed")
    elif native_replay_status is not ReplayStatus.PASS:
        reasons.append(f"native_replay_{native_replay_status.value}")
    if independent_replay_status is ReplayStatus.FAIL:
        reasons.append("independent_replay_failed")
    elif independent_replay_status is not ReplayStatus.PASS:
        reasons.append(f"independent_replay_{independent_replay_status.value}")
    if security_relevance is False:
        reasons.append("security_relevance_failed")
    elif security_relevance is None:
        reasons.append("security_relevance_unassessed")
    missing_capabilities = sorted(set(required_capabilities) - set(allowed_capabilities))
    if missing_capabilities:
        reasons.append("capability_not_allowed:" + ",".join(missing_capabilities))

    hard_failure = any(
        reason.endswith("failed")
        or reason.endswith("invalid")
        or reason.startswith("capability_not_allowed")
        for reason in reasons
    )
    if hard_failure:
        status = WitnessAssessmentStatus.REJECTED
    elif reasons:
        status = WitnessAssessmentStatus.PENDING
    else:
        status = WitnessAssessmentStatus.CONFIRMED
        reasons.append("all_required_replay_and_relevance_checks_passed")
    return ReplayAssessment(
        witness_id=witness_id,
        model_trace_valid=model_trace_valid,
        native_replay_status=native_replay_status,
        independent_replay_status=independent_replay_status,
        security_relevance=security_relevance,
        allowed_capabilities=tuple(sorted(set(allowed_capabilities))),
        required_capabilities=tuple(sorted(set(required_capabilities))),
        status=status,
        reasons=tuple(reasons),
        native_witness_seconds=native_witness_seconds,
        evaluator_reproduction_seconds=evaluator_reproduction_seconds,
    )


__all__ = ["ReplayAssessment", "WitnessAssessmentStatus", "assess_witness"]
