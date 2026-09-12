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
from .cache import CacheLookup, FileVerificationCache, VerificationCacheKey
from .metrics import (
    CampaignAvailability,
    VerificationCampaign,
    VerificationMetric,
    VerificationMetrics,
    compute_verification_metrics,
)
from .fixture import FixtureVerificationConfig, FixtureVerificationExecutors
from .inputs import candidates_from_method_run
from .runner import verify_candidates, verify_method_campaign, verify_method_run
from .timing import MethodTiming, TimingObservation, summarize_campaign_archive_timing, summarize_method_timing
from .source import SourceBackedVerificationExecutors, SourceCommandSpec
from .source_workspace import SourceCaseIdentity, load_source_case_identity, materialize_source_case_workspace

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
    "CacheLookup",
    "FileVerificationCache",
    "VerificationCacheKey",
    "CampaignAvailability",
    "VerificationCampaign",
    "VerificationMetric",
    "VerificationMetrics",
    "compute_verification_metrics",
    "FixtureVerificationConfig",
    "FixtureVerificationExecutors",
    "candidates_from_method_run",
    "verify_candidates",
    "verify_method_campaign",
    "verify_method_run",
    "MethodTiming",
    "TimingObservation",
    "summarize_campaign_archive_timing",
    "summarize_method_timing",
    "SourceBackedVerificationExecutors",
    "SourceCommandSpec",
    "SourceCaseIdentity",
    "load_source_case_identity",
    "materialize_source_case_workspace",
    "load_archives",
    "match_campaigns",
]
