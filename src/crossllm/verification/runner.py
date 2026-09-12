"""Run proposal methods through the shared candidate verification pipeline."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..methods.runner import MethodRun
from .cache import FileVerificationCache
from .inputs import candidates_from_method_run
from .metrics import CampaignAvailability, VerificationCampaign
from .pipeline import SharedVerificationPipeline, VerificationExecutors
from .records import CandidateInput, PairKey, VerificationOutcome
from .runtime import CaseRuntimeBindings


def verify_candidates(
    candidates: Iterable[CandidateInput],
    case: CaseRuntimeBindings,
    symbols: list[Any],
    *,
    executors: VerificationExecutors | None = None,
    cache: FileVerificationCache | None = None,
    adapter_revision: str = "runtime-adapter-v1",
    bounds: dict[str, Any] | None = None,
    replay_spec_hash: str | None = None,
) -> tuple[VerificationOutcome, ...]:
    """Verify ordered candidates with one shared adapter/pipeline instance.

    Keeping one pipeline instance per case is important for stateful backend
    hooks such as fixture search and witness projection.  It also guarantees
    that X, P and T0 receive identical adapter revision, bounds and cache
    semantics; only their candidate archive is different.
    """

    pipeline = SharedVerificationPipeline(
        case,
        symbols,
        executors=executors,
        cache=cache,
        adapter_revision=adapter_revision,
        bounds=bounds,
        replay_spec_hash=replay_spec_hash,
    )
    return tuple(pipeline.verify(candidate) for candidate in candidates)


def verify_method_run(
    method_run: MethodRun,
    *,
    campaign_id: str,
    pair_key: PairKey,
    arm: str,
    case: CaseRuntimeBindings,
    symbols: list[Any],
    executors: VerificationExecutors | None = None,
    cache: FileVerificationCache | None = None,
    adapter_revision: str = "runtime-adapter-v1",
    bounds: dict[str, Any] | None = None,
    replay_spec_hash: str | None = None,
) -> tuple[VerificationOutcome, ...]:
    """Convert X/P/T0 output and send it through the common verifier."""

    candidates = candidates_from_method_run(
        method_run,
        campaign_id=campaign_id,
        pair_key=pair_key,
        arm=arm,
    )
    return verify_candidates(
        candidates,
        case,
        symbols,
        executors=executors,
        cache=cache,
        adapter_revision=adapter_revision,
        bounds=bounds,
        replay_spec_hash=replay_spec_hash,
    )


def verify_method_campaign(
    method_run: MethodRun,
    *,
    campaign_id: str,
    pair_key: PairKey,
    arm: str,
    ground_truth: str,
    property_family: str,
    model_tag: str,
    case: CaseRuntimeBindings,
    symbols: list[Any],
    executors: VerificationExecutors | None = None,
    cache: FileVerificationCache | None = None,
    adapter_revision: str = "runtime-adapter-v1",
    bounds: dict[str, Any] | None = None,
    replay_spec_hash: str | None = None,
) -> VerificationCampaign:
    """Run one method archive and materialize the shared metrics input."""

    outcomes = verify_method_run(
        method_run,
        campaign_id=campaign_id,
        pair_key=pair_key,
        arm=arm,
        case=case,
        symbols=symbols,
        executors=executors,
        cache=cache,
        adapter_revision=adapter_revision,
        bounds=bounds,
        replay_spec_hash=replay_spec_hash,
    )
    availability, reason = _availability(method_run, outcomes)
    return VerificationCampaign(
        campaign_id=campaign_id,
        arm=arm,
        pair_key=pair_key,
        ground_truth=ground_truth,
        slot_count=len(outcomes),
        outcomes=outcomes,
        availability=availability,
        missing_reason=reason,
        model_tag=model_tag,
        property_family=property_family,
    )


def _availability(
    method_run: MethodRun,
    outcomes: tuple[VerificationOutcome, ...],
) -> tuple[CampaignAvailability, str | None]:
    """Classify method-level missingness without treating abstention as failure."""

    for response in method_run.provider_responses:
        row = response.as_dict() if hasattr(response, "as_dict") else response
        if isinstance(row, dict) and (row.get("error") is not None or row.get("http_status") not in {None, 200}):
            return CampaignAvailability.UNKNOWN, "provider_failure_or_partial_archive"
    statuses = {stage.status for outcome in outcomes for stage in outcome.stages}
    if any(status.value == "crash" for status in statuses):
        return CampaignAvailability.UNKNOWN, "verification_stage_crash"
    if any(status.value in {"timeout", "unknown"} for status in statuses):
        return CampaignAvailability.UNKNOWN, "verification_stage_incomplete"
    if any(status.value == "unsupported" for status in statuses):
        return CampaignAvailability.UNSUPPORTED, "runtime_or_backend_unsupported"
    return CampaignAvailability.AVAILABLE, None


__all__ = ["verify_candidates", "verify_method_campaign", "verify_method_run"]
