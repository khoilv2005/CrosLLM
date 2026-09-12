"""Shared proposal-to-verification contracts and archive loading."""

from .records import (
    ArchiveValidationError,
    CandidateInput,
    CampaignArchive,
    CampaignInput,
    CaseRuntimeSpec,
    PairKey,
    StageResult,
    StageStatus,
    VerificationOutcome,
)
from .loader import ArchiveRoot, VerificationDataset, load_archives, match_campaigns
from .runtime import (
    ActionRuntimeBinding,
    BindingStatus,
    CaseRuntimeBindings,
    RuntimeBindingMatrix,
    SymbolRuntimeBinding,
    build_runtime_binding_matrix,
    load_case_runtime,
)
from .adapter import AdapterStatus, RuntimeCandidateAdapter, RuntimeCandidatePlan, public_xlir_symbols
from .pipeline import SharedVerificationPipeline, VerificationExecutors

__all__ = [
    "ArchiveRoot",
    "ArchiveValidationError",
    "CandidateInput",
    "CampaignArchive",
    "CampaignInput",
    "CaseRuntimeSpec",
    "PairKey",
    "StageResult",
    "StageStatus",
    "VerificationDataset",
    "VerificationOutcome",
    "ActionRuntimeBinding",
    "BindingStatus",
    "CaseRuntimeBindings",
    "RuntimeBindingMatrix",
    "SymbolRuntimeBinding",
    "build_runtime_binding_matrix",
    "load_case_runtime",
    "AdapterStatus",
    "RuntimeCandidateAdapter",
    "RuntimeCandidatePlan",
    "public_xlir_symbols",
    "SharedVerificationPipeline",
    "VerificationExecutors",
    "load_archives",
    "match_campaigns",
]
