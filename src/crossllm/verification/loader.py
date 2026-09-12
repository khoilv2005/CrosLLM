"""Duplicate-safe loader for proposal-stage campaign archives."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from ..methods.proposal import candidate_identity
from .records import ArchiveValidationError, CampaignArchive, PairKey


@dataclass(frozen=True, slots=True)
class ArchiveRoot:
    """One method arm directory and its stable public label."""

    arm: str
    path: Path

    def __post_init__(self) -> None:
        if not self.arm or not self.path:
            raise ValueError("archive root requires arm and path")


@dataclass(frozen=True, slots=True)
class VerificationDataset:
    """Loaded archives indexed by campaign and pairing key."""

    campaigns: tuple[CampaignArchive, ...]
    roots: tuple[ArchiveRoot, ...]

    def by_campaign_id(self) -> dict[str, CampaignArchive]:
        return {campaign.campaign_id: campaign for campaign in self.campaigns}

    def by_pair_key(self) -> dict[PairKey, tuple[CampaignArchive, ...]]:
        grouped: dict[PairKey, list[CampaignArchive]] = {}
        for campaign in self.campaigns:
            grouped.setdefault(campaign.pair_key, []).append(campaign)
        return {key: tuple(sorted(value, key=lambda row: (row.arm, row.campaign_id))) for key, value in grouped.items()}

    @property
    def candidate_count(self) -> int:
        return sum(campaign.candidate_count for campaign in self.campaigns)

    @property
    def unique_candidate_count(self) -> int:
        identities: set[str] = set()
        for campaign in self.campaigns:
            for candidate in campaign.candidate_inputs():
                if candidate.proposal_status == "candidate":
                    identities.add(candidate_identity(candidate.candidate)[0])
        return len(identities)


def load_archives(
    roots: Mapping[str, Path] | tuple[ArchiveRoot, ...] | list[ArchiveRoot],
    *,
    expected_slots: int = 8,
    planned_campaign_ids: set[str] | None = None,
) -> VerificationDataset:
    """Load all archive rows while preserving raw records and slot ordering.

    Provider failures inside a structurally valid eight-slot archive are retained
    for downstream missingness analysis.  Structural corruption and duplicate
    campaign IDs fail before a verification worker can submit or count a job.
    """
    if expected_slots <= 0:
        raise ValueError("expected_slots must be positive")
    archive_roots = _normalize_roots(roots)
    campaigns: list[CampaignArchive] = []
    seen_ids: dict[str, Path] = {}
    seen_pair_arms: dict[tuple[PairKey, str], Path] = {}
    for root in archive_roots:
        if not root.path.is_dir():
            continue
        for path in sorted(root.path.glob("*/campaigns.jsonl")):
            archive = _load_one(path, root.arm, expected_slots)
            if planned_campaign_ids is not None and archive.campaign_id not in planned_campaign_ids:
                raise ArchiveValidationError(f"{path}: campaign is absent from the supplied plan")
            previous = seen_ids.get(archive.campaign_id)
            if previous is not None:
                raise ArchiveValidationError(
                    f"duplicate campaign_id {archive.campaign_id!r}: {previous} and {path}"
                )
            pair_arm = (archive.pair_key, archive.arm)
            previous_pair = seen_pair_arms.get(pair_arm)
            if previous_pair is not None:
                raise ArchiveValidationError(
                    "duplicate pair/arm "
                    f"{archive.pair_key.as_dict()} arm={archive.arm!r}: "
                    f"{previous_pair} and {path}"
                )
            seen_ids[archive.campaign_id] = path
            seen_pair_arms[pair_arm] = path
            campaigns.append(archive)
    campaigns.sort(key=lambda row: (row.pair_key, row.arm, row.campaign_id))
    return VerificationDataset(tuple(campaigns), archive_roots)


def match_campaigns(
    dataset: VerificationDataset,
    *,
    left_arm: str = "crossllm",
    right_arm: str = "direct",
) -> tuple[tuple[CampaignArchive, CampaignArchive], ...]:
    """Return only complete one-to-one arm matches by instance/replicate."""
    grouped: dict[PairKey, dict[str, list[CampaignArchive]]] = {}
    for campaign in dataset.campaigns:
        if campaign.arm in {left_arm, right_arm}:
            grouped.setdefault(campaign.pair_key, {}).setdefault(campaign.arm, []).append(campaign)
    matches: list[tuple[CampaignArchive, CampaignArchive]] = []
    for key in sorted(grouped):
        arms = grouped[key]
        left = arms.get(left_arm, [])
        right = arms.get(right_arm, [])
        if len(left) == 1 and len(right) == 1:
            matches.append((left[0], right[0]))
        elif left or right:
            raise ArchiveValidationError(
                f"ambiguous or incomplete pair {key.as_dict()}: "
                f"{left_arm}={len(left)}, {right_arm}={len(right)}"
            )
    return tuple(matches)


def _normalize_roots(roots: Mapping[str, Path] | tuple[ArchiveRoot, ...] | list[ArchiveRoot]) -> tuple[ArchiveRoot, ...]:
    if isinstance(roots, Mapping):
        normalized = tuple(ArchiveRoot(str(arm), Path(path)) for arm, path in roots.items())
    else:
        normalized = tuple(roots)
    if not normalized or len({root.arm for root in normalized}) != len(normalized):
        raise ValueError("archive roots must have unique non-empty arm labels")
    return normalized


def _load_one(path: Path, arm: str, expected_slots: int) -> CampaignArchive:
    lines = [line for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if len(lines) != 1:
        raise ArchiveValidationError(f"{path}: expected exactly one JSONL row, got {len(lines)}")
    try:
        row = json.loads(lines[0])
    except json.JSONDecodeError as error:
        raise ArchiveValidationError(f"{path}: malformed JSON: {error.msg}") from error
    if not isinstance(row, dict):
        raise ArchiveValidationError(f"{path}: archive row must be an object")
    try:
        campaign = row["campaign"]
        method_run = row["method_run"]
        method_run_settings = method_run["settings"]
        campaign_id = _string(campaign, "campaign_id")
        attempt_id = _string(method_run, "attempt_id")
        pair_key = PairKey(
            _string(campaign, "lineage_id"), _string(campaign, "instance_id"),
            _positive_int(campaign, "replicate"),
        )
        slots = _dict_list(method_run, "slots")
        responses = _dict_list(method_run, "provider_responses")
        budgets = _dict_list(method_run, "budget_checks")
        method = _string(campaign, "method")
        track = method_run.get("track")
        providerless_t0 = method == "t0" and track == "T0" and not responses and not budgets
        if len(slots) != expected_slots or (
            not providerless_t0 and (len(responses) != expected_slots or len(budgets) != expected_slots)
        ):
            raise ArchiveValidationError(
                f"{path}: expected {expected_slots} slots/responses/budgets, "
                f"got {len(slots)}/{len(responses)}/{len(budgets)}"
            )
        if not isinstance(row.get("public_artifact_pack"), dict):
            raise ArchiveValidationError(f"{path}: public_artifact_pack is missing")
        if not isinstance(method_run_settings, dict):
            raise ArchiveValidationError(f"{path}: method_run.settings must be an object")
        for index, (slot, response, budget) in enumerate(
            zip(slots, responses, budgets) if not providerless_t0 else ((slot, {}, {}) for slot in slots)
        ):
            if slot.get("index") != index:
                raise ArchiveValidationError(f"{path}: slot {index} has non-canonical index")
            if providerless_t0:
                continue
            http_status = response.get("http_status")
            if http_status is not None and (not isinstance(http_status, int) or isinstance(http_status, bool)):
                raise ArchiveValidationError(f"{path}: slot {index} has invalid http_status")
            if http_status is None and not isinstance(response.get("error"), str):
                raise ArchiveValidationError(f"{path}: slot {index} has no HTTP status or transport error")
            if not isinstance(budget.get("status"), str):
                raise ArchiveValidationError(f"{path}: slot {index} budget status is missing")
        pack_hash = row.get("public_artifact_pack_hash")
        if not isinstance(pack_hash, str) or not pack_hash:
            pack_hash = _string(method_run, "artifact_pack_hash")
        return CampaignArchive(
            campaign_id=campaign_id,
            attempt_id=attempt_id,
            pair_key=pair_key,
            arm=arm,
            method=method,
            backbone=_string(campaign, "backbone"),
            model_tag=_string(campaign, "model_tag"),
            config_hash=_string(campaign, "config_hash"),
            request_settings_hash=_string(campaign, "request_settings_hash"),
            artifact_pack_hash=pack_hash,
            slots=tuple(slots),
            provider_responses=tuple(responses),
            budget_checks=tuple(budgets),
            raw_row=row,
            archive_path=str(path),
        )
    except ArchiveValidationError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise ArchiveValidationError(f"{path}: invalid archive schema: {error}") from error


def _string(value: Mapping[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise ArchiveValidationError(f"{field} must be a non-empty string")
    return item


def _positive_int(value: Mapping[str, Any], field: str) -> int:
    item = value.get(field)
    if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
        raise ArchiveValidationError(f"{field} must be a positive integer")
    return item


def _dict_list(value: Mapping[str, Any], field: str) -> list[Mapping[str, Any]]:
    item = value.get(field)
    if not isinstance(item, list) or not all(isinstance(row, dict) for row in item):
        raise ArchiveValidationError(f"{field} must be a list of objects")
    return item


__all__ = ["ArchiveRoot", "VerificationDataset", "load_archives", "match_campaigns"]
