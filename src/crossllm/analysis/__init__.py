"""Prespecified, order-independent analysis helpers."""

from .estimands import AnalysisReport, CampaignOutcome, OutcomeAvailability, TimeEndpoint, analyze_outcomes
from .inference import BootstrapSummary, SignTestResult, exact_two_sided_sign_test, holm_adjust, paired_lineage_bootstrap
from .reporting import ContrastInference, analyze_contrast_family, leave_one_lineage_out, zero_event_upper_bound
from .sampling import SampledRecord, stratified_sample
from .agreement import AgreementSummary, agreement_summary
from .artifacts import (
    AnalysisArtifact,
    AnalysisArtifactBuilder,
    AnalysisInputError,
    PRIMARY_CONTRAST_COUNT,
    SECONDARY_CONTRAST_COUNT,
    campaign_outcome_from_dict,
    load_campaign_jsonl,
    write_analysis_bundle,
)
from .tables import AnalysisTable, build_analysis_tables
from .figures import AnalysisFigure, AnalysisFigureBuilder, write_figure_bundle
from .proposal_recall import (
    BatchAvailability,
    EndToEndObservation,
    EndToEndRecallResult,
    PrefixRecallResult,
    ProposalBatch,
    RecallMetric,
    end_to_end_budget_recall,
    proposal_prefix_recall,
)

__all__ = [
    "AnalysisReport", "BootstrapSummary", "CampaignOutcome", "ContrastInference", "OutcomeAvailability", "TimeEndpoint",
    "AgreementSummary", "SampledRecord",
    "SignTestResult", "analyze_outcomes", "exact_two_sided_sign_test", "holm_adjust",
    "paired_lineage_bootstrap", "analyze_contrast_family", "agreement_summary", "leave_one_lineage_out",
    "stratified_sample", "zero_event_upper_bound",
    "AnalysisArtifact", "AnalysisArtifactBuilder", "AnalysisInputError",
    "PRIMARY_CONTRAST_COUNT", "SECONDARY_CONTRAST_COUNT",
    "campaign_outcome_from_dict", "load_campaign_jsonl",
    "write_analysis_bundle",
    "AnalysisTable", "build_analysis_tables",
    "AnalysisFigure", "AnalysisFigureBuilder", "write_figure_bundle",
    "BatchAvailability", "EndToEndObservation", "EndToEndRecallResult",
    "PrefixRecallResult", "ProposalBatch", "RecallMetric",
    "end_to_end_budget_recall", "proposal_prefix_recall",
]
