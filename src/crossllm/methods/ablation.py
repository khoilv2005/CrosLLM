"""P0 ablation-plan contracts for controlled CrossLLM comparisons."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from ..contracts.canonical import sha256_hex


class AblationPhase(StrEnum):
    PRIMARY = "primary"
    POST_PRIMARY_DIAGNOSTIC = "post_primary_diagnostic"


@dataclass(frozen=True, slots=True)
class AblationArm:
    arm_id: str
    settings: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.arm_id or not isinstance(self.settings, Mapping) or not self.settings:
            raise ValueError("ablation arm requires identity and settings")

    def as_dict(self) -> dict[str, object]:
        return {"arm_id": self.arm_id, "settings": dict(self.settings)}


@dataclass(frozen=True, slots=True)
class AblationStudy:
    study_id: str
    varied_component: str
    left: AblationArm
    right: AblationArm
    phase: AblationPhase = AblationPhase.PRIMARY
    shared_inputs: tuple[str, ...] = ()
    gold_access: bool = False

    def __post_init__(self) -> None:
        if not self.study_id or not self.varied_component:
            raise ValueError("ablation study identity and varied component are required")
        if self.left.arm_id == self.right.arm_id:
            raise ValueError("ablation arms must have distinct IDs")
        keys = set(self.left.settings) | set(self.right.settings)
        differences = {
            key for key in keys if self.left.settings.get(key) != self.right.settings.get(key)
        }
        if differences != {self.varied_component}:
            raise ValueError("ablation arms must differ in exactly the declared component")
        if any(not value for value in self.shared_inputs):
            raise ValueError("shared input names must be non-empty")
        if self.phase is AblationPhase.PRIMARY and self.gold_access:
            raise ValueError("primary ablations cannot access gold properties")
        if self.phase is AblationPhase.POST_PRIMARY_DIAGNOSTIC and not self.gold_access:
            raise ValueError("post-primary diagnostic must declare gold access")

    @property
    def plan_hash(self) -> str:
        return sha256_hex(self.as_dict(include_hash=False))

    def as_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        payload = {
            "schema_version": 1,
            "study_id": self.study_id,
            "varied_component": self.varied_component,
            "left": self.left.as_dict(),
            "right": self.right.as_dict(),
            "phase": self.phase.value,
            "shared_inputs": list(self.shared_inputs),
            "gold_access": self.gold_access,
        }
        if include_hash:
            payload["plan_hash"] = self.plan_hash
        return payload


@dataclass(frozen=True, slots=True)
class AblationPlan:
    plan_id: str
    studies: tuple[AblationStudy, ...]

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise ValueError("ablation plan identity is required")
        ids = [study.study_id for study in self.studies]
        if len(ids) != len(set(ids)):
            raise ValueError("ablation study IDs must be unique")

    @property
    def plan_hash(self) -> str:
        return sha256_hex({"schema_version": 1, "plan_id": self.plan_id, "studies": [study.as_dict() for study in self.studies]})

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
            "studies": [study.as_dict() for study in self.studies],
        }


def build_p0_ablation_plan(*, plan_id: str = "m07-p0-ablation-v1") -> AblationPlan:
    """Return the prespecified primary contrasts and post-primary diagnostic."""
    shared_pipeline = ("artifact_pack", "threat_profile", "backend_budget", "instance_selection")
    studies = (
        AblationStudy(
            "learned-vs-t0", "proposer",
            AblationArm("learned", {"proposer": "learned", "downstream": "fixed"}),
            AblationArm("t0", {"proposer": "t0", "downstream": "fixed"}),
            shared_inputs=shared_pipeline,
        ),
        AblationStudy(
            "primitive-vs-generic-typed-core", "property_representation",
            AblationArm("primitive", {"property_representation": "bridge_macros", "expressiveness": "shared"}),
            AblationArm("generic", {"property_representation": "generic_typed_core", "expressiveness": "shared"}),
            shared_inputs=shared_pipeline + ("expressiveness_contract",),
        ),
        AblationStudy(
            "grounding-early-vs-deferred", "grounding_timing",
            AblationArm("early", {"grounding_timing": "early", "proposal_pool": "stored"}),
            AblationArm("deferred", {"grounding_timing": "deferred", "proposal_pool": "stored"}),
            shared_inputs=shared_pipeline + ("stored_proposal_pool",),
        ),
        AblationStudy(
            "replay-on-vs-off", "replay_filter",
            AblationArm("replay-on", {"replay_filter": "on", "candidate_pool": "stored_symbolic"}),
            AblationArm("replay-off", {"replay_filter": "off", "candidate_pool": "stored_symbolic"}),
            shared_inputs=shared_pipeline + ("stored_symbolic_candidate_pool",),
        ),
        AblationStudy(
            "adversarial-channel-vs-fifo", "channel_mode",
            AblationArm("adversarial", {"channel_mode": "adversarial", "transition_budget": "fixed"}),
            AblationArm("fifo", {"channel_mode": "fifo", "transition_budget": "fixed"}),
            shared_inputs=shared_pipeline,
        ),
        AblationStudy(
            "gold-diagnostic-after-primary-freeze", "property_source",
            AblationArm("automatic", {"property_source": "automatic", "primary_results": "locked"}),
            AblationArm("gold", {"property_source": "gold", "primary_results": "locked"}),
            phase=AblationPhase.POST_PRIMARY_DIAGNOSTIC,
            shared_inputs=shared_pipeline + ("primary_output_commitment",),
            gold_access=True,
        ),
    )
    return AblationPlan(plan_id, studies)


__all__ = ["AblationArm", "AblationPhase", "AblationPlan", "AblationStudy", "build_p0_ablation_plan"]
