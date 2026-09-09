"""Native baseline and conditioned-tool execution boundaries."""

from .external import (
    BaselineFinding,
    BaselineResult,
    ExternalToolAdapter,
    ResourceEnvelope,
    ToolSpec,
    normalize_findings,
)
from .subset import SubsetSelection, select_balanced_subset
from .support import SupportEntry, SupportMatrix, SupportStatus
from .sensitivity import (
    CellBudget,
    CellEligibility,
    EligibilityStatus,
    SensitivityCell,
    SensitivityMatrix,
    build_sensitivity_matrix,
)
from .gptscan import FidelityStatus, GPTScanAdapter, GPTScanAudit, GPTScanParityReport, GPTScanSpec, compare_parity
from .conditioned import ConditionedAdapter, ConditionedResult, ConditionedSpec, EffortVector

__all__ = [
    "BaselineFinding",
    "BaselineResult",
    "ExternalToolAdapter",
    "ResourceEnvelope",
    "ToolSpec",
    "normalize_findings",
    "SubsetSelection",
    "select_balanced_subset",
    "SupportEntry",
    "SupportMatrix",
    "SupportStatus",
    "CellBudget",
    "CellEligibility",
    "EligibilityStatus",
    "SensitivityCell",
    "SensitivityMatrix",
    "build_sensitivity_matrix",
    "FidelityStatus",
    "GPTScanAdapter",
    "GPTScanAudit",
    "GPTScanParityReport",
    "GPTScanSpec",
    "compare_parity",
    "ConditionedAdapter",
    "ConditionedResult",
    "ConditionedSpec",
    "EffortVector",
]
