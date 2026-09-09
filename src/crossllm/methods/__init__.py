"""Method-level proposal slot contracts."""

from .proposal import (
    PromptPolicy,
    PromptTemplate,
    ProposalSlot,
    ProposalSlotStatus,
    OrderedProposalSlots,
    candidate_identity,
    classify_response,
)
from .runner import MethodRun, MethodRunner, MethodTrack
from .ablation import AblationArm, AblationPhase, AblationPlan, AblationStudy, build_p0_ablation_plan

__all__ = [
    "OrderedProposalSlots",
    "MethodRun",
    "MethodRunner",
    "MethodTrack",
    "PromptPolicy",
    "PromptTemplate",
    "ProposalSlot",
    "ProposalSlotStatus",
    "classify_response",
    "candidate_identity",
    "AblationArm",
    "AblationPhase",
    "AblationPlan",
    "AblationStudy",
    "build_p0_ablation_plan",
]
