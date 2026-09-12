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
    "load_archives",
    "match_campaigns",
]
