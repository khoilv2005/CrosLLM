"""Versioned records shared by every proposal verification method."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Any, Mapping

from ..methods.proposal import candidate_identity


class ArchiveValidationError(ValueError):
    """An archive cannot be safely admitted to the verification queue."""


class StageStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    TIMEOUT = "timeout"
    CRASH = "crash"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True, order=True)
class PairKey:
    """The stable key shared by CrossLLM, Direct and T0 arm records."""

    lineage_id: str
    instance_id: str
    replicate: int

    def __post_init__(self) -> None:
        if not self.lineage_id or not self.instance_id:
            raise ValueError("pair key requires lineage_id and instance_id")
        if not isinstance(self.replicate, int) or isinstance(self.replicate, bool) or self.replicate <= 0:
            raise ValueError("pair key replicate must be a positive integer")

    def as_dict(self) -> dict[str, object]:
        return {
            "lineage_id": self.lineage_id,
            "instance_id": self.instance_id,
            "replicate": self.replicate,
        }


@dataclass(frozen=True, slots=True)
class CaseRuntimeSpec:
    """Hash-bound runtime identity consumed by a future case adapter."""

    case_id: str
    lineage_id: str
    instance_id: str
    source_artifact_hash: str
    build_manifest_hash: str
    deployment_hash: str
    profile_hash: str
    compiler_hash: str
    source_domain: str
    destination_domain: str
    supported_actions: tuple[str, ...] = ()
    observation_points: tuple[str, ...] = ()
    contract_addresses: Mapping[str, str] = field(default_factory=dict)
    actors: Mapping[str, str] = field(default_factory=dict)
    initial_state: Mapping[str, Any] = field(default_factory=dict)
    runtime_mode: str = "unknown"
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value for value in (
            self.case_id, self.lineage_id, self.instance_id,
            self.source_domain, self.destination_domain,
        )):
            raise ValueError("runtime spec identity and domains are required")
        if self.source_domain == self.destination_domain:
            raise ValueError("runtime spec domains must be distinct")
        for name in ("source_artifact_hash", "build_manifest_hash", "deployment_hash", "profile_hash", "compiler_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        for name, values in (("supported_actions", self.supported_actions), ("observation_points", self.observation_points)):
            if not isinstance(values, tuple) or any(not isinstance(value, str) or not value for value in values):
                raise ValueError(f"{name} must contain non-empty strings")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must not contain duplicates")
        for name, values in (("contract_addresses", self.contract_addresses), ("actors", self.actors), ("initial_state", self.initial_state)):
            if not isinstance(values, Mapping):
                raise ValueError(f"{name} must be a mapping")
        for name, values in (("contract_addresses", self.contract_addresses), ("actors", self.actors)):
            if any(not isinstance(key, str) or not key or not isinstance(value, str) or not value for key, value in values.items()):
                raise ValueError(f"{name} keys and values must be non-empty strings")
        if not isinstance(self.runtime_mode, str) or not self.runtime_mode:
            raise ValueError("runtime_mode must be a non-empty string")
        if self.metadata is not None and not isinstance(self.metadata, Mapping):
            raise ValueError("runtime spec metadata must be a mapping")

    @property
    def runtime_hash(self) -> str:
        return candidate_identity({
            "case_id": self.case_id,
            "lineage_id": self.lineage_id,
            "instance_id": self.instance_id,
            "source_artifact_hash": self.source_artifact_hash,
            "build_manifest_hash": self.build_manifest_hash,
            "deployment_hash": self.deployment_hash,
            "profile_hash": self.profile_hash,
            "compiler_hash": self.compiler_hash,
            "source_domain": self.source_domain,
            "destination_domain": self.destination_domain,
            "supported_actions": list(self.supported_actions),
            "observation_points": list(self.observation_points),
            "contract_addresses": dict(self.contract_addresses),
            "actors": dict(self.actors),
            "initial_state": dict(self.initial_state),
            "runtime_mode": self.runtime_mode,
            "metadata": dict(self.metadata) if self.metadata is not None else None,
        })[0]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "record_type": "case_runtime_spec",
            "case_id": self.case_id,
            "lineage_id": self.lineage_id,
            "instance_id": self.instance_id,
            "source_artifact_hash": self.source_artifact_hash,
            "build_manifest_hash": self.build_manifest_hash,
            "deployment_hash": self.deployment_hash,
            "profile_hash": self.profile_hash,
            "compiler_hash": self.compiler_hash,
            "source_domain": self.source_domain,
            "destination_domain": self.destination_domain,
            "supported_actions": list(self.supported_actions),
            "observation_points": list(self.observation_points),
            "contract_addresses": dict(self.contract_addresses),
            "actors": dict(self.actors),
            "initial_state": dict(self.initial_state),
            "runtime_mode": self.runtime_mode,
            "metadata": dict(self.metadata) if self.metadata is not None else None,
            "runtime_hash": self.runtime_hash,
        }


@dataclass(frozen=True, slots=True)
class CampaignArchive:
    """One complete proposal-stage archive plus its untouched raw row."""

    campaign_id: str
    attempt_id: str
    pair_key: PairKey
    arm: str
    method: str
    backbone: str
    model_tag: str
    config_hash: str
    request_settings_hash: str
    artifact_pack_hash: str
    slots: tuple[Mapping[str, Any], ...]
    provider_responses: tuple[Mapping[str, Any], ...]
    budget_checks: tuple[Mapping[str, Any], ...]
    raw_row: Mapping[str, Any]
    archive_path: str

    def __post_init__(self) -> None:
        required = (
            self.campaign_id, self.attempt_id, self.arm, self.method,
            self.backbone, self.model_tag, self.config_hash,
            self.request_settings_hash, self.artifact_pack_hash,
            self.archive_path,
        )
        if any(not isinstance(value, str) or not value for value in required):
            raise ValueError("campaign archive identity is incomplete")
        if len(self.slots) != len(self.provider_responses) or len(self.slots) != len(self.budget_checks):
            raise ValueError("archive slot collections must have equal length")
        if not self.slots:
            raise ValueError("archive must contain at least one slot")

    @property
    def slot_count(self) -> int:
        return len(self.slots)

    @property
    def provider_failure_count(self) -> int:
        return sum(
            response.get("error") is not None or response.get("http_status") != 200
            for response in self.provider_responses
        )

    @property
    def candidate_count(self) -> int:
        return sum(slot.get("status") == "candidate" for slot in self.slots)

    @property
    def unique_candidate_count(self) -> int:
        identities: set[str] = set()
        for candidate in self.candidate_inputs():
            if candidate.proposal_status == "candidate":
                identities.add(candidate_identity(candidate.candidate)[0])
        return len(identities)

    def candidate_inputs(self) -> tuple["CandidateInput", ...]:
        return tuple(
            CandidateInput(
                campaign_id=self.campaign_id,
                attempt_id=self.attempt_id,
                pair_key=self.pair_key,
                arm=self.arm,
                slot_index=index,
                slot_id=str(slot.get("slot_id", f"{self.attempt_id}:slot:{index}")),
                proposal_status=str(slot.get("status", "invalid")),
                canonical_ast_hash=slot.get("canonical_ast_hash") if isinstance(slot.get("canonical_ast_hash"), str) else None,
                raw_response_hash=response.get("response_hash") if isinstance(response.get("response_hash"), str) else None,
                candidate=slot.get("candidate"),
                raw_response=response,
            )
            for index, (slot, response) in enumerate(zip(self.slots, self.provider_responses))
        )


@dataclass(frozen=True, slots=True)
class CandidateInput:
    """One ordered proposal slot entering the shared verification pipeline."""

    campaign_id: str
    attempt_id: str
    pair_key: PairKey
    arm: str
    slot_index: int
    slot_id: str
    proposal_status: str
    canonical_ast_hash: str | None
    raw_response_hash: str | None
    candidate: object | None
    raw_response: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.campaign_id or not self.attempt_id or not self.arm or not self.slot_id:
            raise ValueError("candidate identity is incomplete")
        if not isinstance(self.slot_index, int) or isinstance(self.slot_index, bool) or self.slot_index < 0:
            raise ValueError("candidate slot_index must be non-negative")
        if self.proposal_status == "candidate" and self.candidate is None:
            raise ValueError("candidate slot is missing its candidate payload")
        if self.proposal_status != "candidate" and self.candidate is not None:
            raise ValueError("non-candidate slot cannot carry candidate payload")

    @property
    def prefix_position(self) -> int:
        return self.slot_index + 1


@dataclass(frozen=True, slots=True)
class StageResult:
    """One verification stage result with explicit timing and missingness."""

    stage: str
    status: StageStatus
    reason: str | None = None
    elapsed_seconds: float | None = None
    evidence: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.stage:
            raise ValueError("stage name is required")
        if self.elapsed_seconds is not None and self.elapsed_seconds < 0:
            raise ValueError("stage elapsed_seconds must be non-negative")
        if self.status is StageStatus.PASSED and self.reason is not None:
            raise ValueError("passed stage cannot carry a failure reason")

    def as_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "status": self.status.value,
            "reason": self.reason,
            "elapsed_seconds": self.elapsed_seconds,
            "evidence": dict(self.evidence) if self.evidence is not None else None,
        }


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    """Candidate-level result consumed by metrics and adjudication."""

    candidate: CandidateInput
    stages: tuple[StageResult, ...]
    candidate_violation: bool | None = None
    property_holds: bool | None = None
    security_relevance: bool | None = None
    verified_finding: bool | None = None
    first_failure: str | None = None
    cache_hit: bool = False

    def __post_init__(self) -> None:
        names = [stage.stage for stage in self.stages]
        if len(names) != len(set(names)):
            raise ValueError("verification stages must be unique per candidate")
        if self.verified_finding is True:
            if not all(
                self.stage_status(name) is StageStatus.PASSED
                for name in ("grounding", "symbolic_search", "witness_check", "independent_replay")
            ):
                raise ValueError("verified finding requires all required stages to pass")
            if self.candidate_violation is not True:
                raise ValueError("verified finding requires candidate_violation=true")
            if self.property_holds is not False:
                raise ValueError("verified finding requires property_holds=false")
            if self.security_relevance is not True:
                raise ValueError("verified finding requires security_relevance=true")
        if not isinstance(self.cache_hit, bool):
            raise ValueError("cache_hit must be boolean")

    def stage_status(self, name: str) -> StageStatus:
        for stage in self.stages:
            if stage.stage == name:
                return stage.status
        return StageStatus.PENDING

    @property
    def availability(self) -> str:
        if self.verified_finding is True:
            return "available"
        if any(stage.status is StageStatus.TIMEOUT for stage in self.stages):
            return "timeout"
        if any(stage.status is StageStatus.UNSUPPORTED for stage in self.stages):
            return "unsupported"
        if any(stage.status is StageStatus.CRASH for stage in self.stages):
            return "unknown"
        return "unknown"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "record_type": "verification_outcome",
            "campaign_id": self.candidate.campaign_id,
            "attempt_id": self.candidate.attempt_id,
            "arm": self.candidate.arm,
            "instance_id": self.candidate.pair_key.instance_id,
            "lineage_id": self.candidate.pair_key.lineage_id,
            "replicate": self.candidate.pair_key.replicate,
            "slot_index": self.candidate.slot_index,
            "slot_id": self.candidate.slot_id,
            "canonical_ast_hash": self.candidate.canonical_ast_hash,
            "stages": [stage.as_dict() for stage in self.stages],
            "candidate_violation": self.candidate_violation,
            "property_holds": self.property_holds,
            "security_relevance": self.security_relevance,
            "verified_finding": self.verified_finding,
            "availability": self.availability,
            "first_failure": self.first_failure,
            "cache_hit": self.cache_hit,
        }

    @classmethod
    def from_dict(cls, candidate: CandidateInput, payload: Mapping[str, Any], *, cache_hit: bool = False) -> "VerificationOutcome":
        """Restore an outcome for the same candidate from a validated cache row."""
        raw_stages = payload.get("stages")
        if not isinstance(raw_stages, list):
            raise ValueError("cached verification outcome has no stages")
        stages: list[StageResult] = []
        for row in raw_stages:
            if not isinstance(row, Mapping):
                raise ValueError("cached verification stage must be an object")
            stages.append(StageResult(
                stage=str(row["stage"]),
                status=StageStatus(row["status"]),
                reason=row.get("reason") if isinstance(row.get("reason"), str) else None,
                elapsed_seconds=row.get("elapsed_seconds") if isinstance(row.get("elapsed_seconds"), (int, float)) else None,
                evidence=row.get("evidence") if isinstance(row.get("evidence"), Mapping) else None,
            ))
        return cls(
            candidate=candidate,
            stages=tuple(stages),
            candidate_violation=payload.get("candidate_violation") if isinstance(payload.get("candidate_violation"), bool) else None,
            property_holds=payload.get("property_holds") if isinstance(payload.get("property_holds"), bool) else None,
            security_relevance=payload.get("security_relevance") if isinstance(payload.get("security_relevance"), bool) else None,
            verified_finding=payload.get("verified_finding") if isinstance(payload.get("verified_finding"), bool) else None,
            first_failure=payload.get("first_failure") if isinstance(payload.get("first_failure"), str) else None,
            cache_hit=cache_hit,
        )


__all__ = [
    "ArchiveValidationError", "CandidateInput", "CampaignArchive", "CampaignInput", "CaseRuntimeSpec", "PairKey",
    "StageResult", "StageStatus", "VerificationOutcome",
]


CampaignInput = CampaignArchive
