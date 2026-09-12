"""Method-level proposal slot contracts."""

from .proposal import (
    PromptPolicy,
    PromptTemplate,
    ProposalSlot,
    ProposalSlotStatus,
    OrderedProposalSlots,
    candidate_identity,
    classify_response,
    parse_json_response,
)
from .runner import MethodRun, MethodRunner, MethodTrack
from .ablation import AblationArm, AblationPhase, AblationPlan, AblationStudy, build_p0_ablation_plan
from .t0 import T0DeterministicProposer, T0InputError, T0ProposalRun, T0Template, T0TemplateLibrary

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
    "parse_json_response",
    "AblationArm",
    "AblationPhase",
    "AblationPlan",
    "AblationStudy",
    "build_p0_ablation_plan",
    "T0DeterministicProposer",
    "T0InputError",
    "T0ProposalRun",
    "T0Template",
    "T0TemplateLibrary",
]
