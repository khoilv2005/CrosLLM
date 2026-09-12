"""Bridge shared verification outcomes into the M09 analysis contract."""

from __future__ import annotations

from collections.abc import Iterable

from ..verification.metrics import CampaignAvailability, VerificationCampaign
from ..verification.records import StageStatus, VerificationOutcome
from .estimands import CampaignOutcome, OutcomeAvailability


def campaigns_to_analysis_outcomes(
    campaigns: Iterable[VerificationCampaign],
    *,
    prefix: int = 8,
    horizon_seconds: float = 3600.0,
) -> tuple[CampaignOutcome, ...]:
    """Project candidate-stage evidence into one row per campaign.

    The projection is intentionally conservative: verified finding is the only
    claim endpoint, and unavailable campaign/stage results become ``None``.
    A witness or replay pass may still be reported independently when a later
    stage is missing; this preserves stage-conditional denominators.
    """

    if not isinstance(prefix, int) or isinstance(prefix, bool) or prefix <= 0:
        raise ValueError("prefix must be a positive integer")
    if not isinstance(horizon_seconds, (int, float)) or isinstance(horizon_seconds, bool) or horizon_seconds <= 0:
        raise ValueError("horizon_seconds must be positive")
    rows: list[CampaignOutcome] = []
    for campaign in campaigns:
        if prefix > campaign.slot_count:
            raise ValueError("prefix cannot exceed campaign slot_count")
        selected = tuple(
            outcome for outcome in campaign.outcomes
            if outcome.candidate.slot_index < prefix
        )
        availability = _analysis_availability(campaign, selected)
        detected = _any_verified(selected, availability)
        useful = _any_grounded_candidate(selected)
        witness = _any_stage(selected, "witness_check", StageStatus.PASSED)
        replay = _any_stage(selected, "independent_replay", StageStatus.PASSED)
        claim_time = _first_verified_time(selected) if detected is True else None
        witness_time = _first_stage_time(selected, "witness_check")
        rows.append(CampaignOutcome(
            campaign_id=campaign.campaign_id,
            instance_id=campaign.pair_key.instance_id,
            lineage_id=campaign.pair_key.lineage_id,
            method=campaign.arm,
            replicate=campaign.pair_key.replicate,
            ground_truth=campaign.ground_truth,
            detected=detected,
            useful_proposal=useful,
            claim_emitted=detected,
            correct_claim=(campaign.ground_truth == "positive") if detected is True else None,
            native_witness=witness,
            independent_replay=replay,
            claim_time_seconds=claim_time,
            witness_time_seconds=witness_time,
            horizon_seconds=float(horizon_seconds),
            availability=availability,
            first_failure=_first_failure(campaign, selected),
        ))
    return tuple(sorted(rows, key=lambda row: (row.lineage_id, row.instance_id, row.method, row.replicate, row.campaign_id)))


def _analysis_availability(
    campaign: VerificationCampaign,
    outcomes: tuple[VerificationOutcome, ...],
) -> OutcomeAvailability:
    if campaign.availability is CampaignAvailability.AVAILABLE:
        return OutcomeAvailability.AVAILABLE
    reason = campaign.missing_reason or ""
    statuses = {stage.status for outcome in outcomes for stage in outcome.stages}
    if "provider_failure" in reason:
        return OutcomeAvailability.PROVIDER_FAILURE
    if StageStatus.TIMEOUT in statuses or "timeout" in reason:
        return OutcomeAvailability.TIMEOUT
    if campaign.availability is CampaignAvailability.UNSUPPORTED:
        return OutcomeAvailability.UNSUPPORTED
    return OutcomeAvailability.UNKNOWN


def _any_verified(outcomes: tuple[VerificationOutcome, ...], availability: OutcomeAvailability) -> bool | None:
    if availability is not OutcomeAvailability.AVAILABLE:
        return None
    return any(outcome.verified_finding is True for outcome in outcomes)


def _any_grounded_candidate(outcomes: tuple[VerificationOutcome, ...]) -> bool | None:
    candidates = [outcome for outcome in outcomes if outcome.candidate.proposal_status == "candidate"]
    if not candidates:
        return False
    return any(outcome.stage_status("grounding") is StageStatus.PASSED for outcome in candidates)


def _any_stage(
    outcomes: tuple[VerificationOutcome, ...],
    name: str,
    status: StageStatus,
) -> bool | None:
    if not outcomes:
        return False
    selected = [outcome for outcome in outcomes if outcome.candidate.proposal_status == "candidate"]
    if not selected:
        return False
    return any(outcome.stage_status(name) is status for outcome in selected)


def _first_stage_time(outcomes: tuple[VerificationOutcome, ...], name: str) -> float | None:
    for outcome in sorted(outcomes, key=lambda row: row.candidate.slot_index):
        stage = next((stage for stage in outcome.stages if stage.stage == name), None)
        if stage is not None and stage.status is StageStatus.PASSED and stage.elapsed_seconds is not None:
            return stage.elapsed_seconds
    return None


def _first_verified_time(outcomes: tuple[VerificationOutcome, ...]) -> float | None:
    for outcome in sorted(outcomes, key=lambda row: row.candidate.slot_index):
        if outcome.verified_finding is not True:
            continue
        values = [
            stage.elapsed_seconds
            for stage in outcome.stages
            if stage.stage in {"symbolic_search", "witness_check", "independent_replay"}
            and stage.elapsed_seconds is not None
        ]
        return sum(values) if values else None
    return None


def _first_failure(campaign: VerificationCampaign, outcomes: tuple[VerificationOutcome, ...]) -> str | None:
    if campaign.missing_reason:
        return campaign.missing_reason
    for outcome in sorted(outcomes, key=lambda row: row.candidate.slot_index):
        if outcome.first_failure:
            return outcome.first_failure
    return None


__all__ = ["campaigns_to_analysis_outcomes"]
