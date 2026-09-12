#!/usr/bin/env python3
"""Build prefix verification metrics from immutable campaign outcome rows.

The input is one ``verification_campaign`` JSON object per JSONL line.  Each
campaign contains an explicit availability value and zero or more candidate
outcomes.  The command never infers a negative result from missing, unsupported,
unknown, timeout or crash records.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from crossllm.verification.metrics import (
    CampaignAvailability,
    VerificationCampaign,
    compute_verification_metrics,
)
from crossllm.verification.records import CandidateInput, PairKey, VerificationOutcome


def load_verification_campaigns(path: Path) -> tuple[VerificationCampaign, ...]:
    """Load and validate campaign envelopes without changing row order semantics."""

    rows: list[VerificationCampaign] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: malformed JSON: {error.msg}") from error
        try:
            rows.append(_campaign_from_dict(payload, path, line_number))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{path}:{line_number}: invalid verification campaign: {error}") from error
    return tuple(rows)


def _campaign_from_dict(payload: object, path: Path, line_number: int) -> VerificationCampaign:
    if not isinstance(payload, Mapping):
        raise ValueError("row must be an object")
    if payload.get("record_type") not in {None, "verification_campaign"}:
        raise ValueError(f"unsupported record_type {payload.get('record_type')!r}")
    campaign_id = _required_string(payload, "campaign_id")
    lineage_id = _required_string(payload, "lineage_id")
    instance_id = _required_string(payload, "instance_id")
    arm = _required_string(payload, "arm")
    replicate = _positive_int(payload, "replicate")
    ground_truth = _ground_truth(payload.get("ground_truth"))
    slot_count = _positive_int(payload, "slot_count")
    availability = CampaignAvailability(payload.get("availability", "available"))
    missing_reason = payload.get("missing_reason")
    if missing_reason is not None and not isinstance(missing_reason, str):
        raise ValueError("missing_reason must be a string or null")
    outcomes_payload = payload.get("outcomes", [])
    if not isinstance(outcomes_payload, list):
        raise ValueError("outcomes must be an array")
    pair_key = PairKey(lineage_id, instance_id, replicate)
    outcomes = tuple(
        _outcome_from_dict(item, campaign_id, arm, pair_key, path, line_number)
        for item in outcomes_payload
    )
    return VerificationCampaign(
        campaign_id=campaign_id,
        arm=arm,
        pair_key=pair_key,
        ground_truth=ground_truth,
        slot_count=slot_count,
        outcomes=outcomes,
        availability=availability,
        missing_reason=missing_reason,
        model_tag=str(payload.get("model_tag", "unknown")),
        property_family=str(payload.get("property_family", "unknown")),
    )


def _outcome_from_dict(
    payload: object,
    campaign_id: str,
    arm: str,
    pair_key: PairKey,
    path: Path,
    line_number: int,
) -> VerificationOutcome:
    if not isinstance(payload, Mapping):
        raise ValueError("outcome must be an object")
    candidate_payload = payload.get("candidate")
    outcome_payload = payload.get("outcome")
    if not isinstance(candidate_payload, Mapping):
        raise ValueError("outcome.candidate must be an object")
    if not isinstance(outcome_payload, Mapping):
        raise ValueError("outcome.outcome must be an object")
    candidate = CandidateInput(
        campaign_id=_required_string(candidate_payload, "campaign_id", fallback=campaign_id),
        attempt_id=_required_string(candidate_payload, "attempt_id"),
        pair_key=PairKey(
            _required_string(candidate_payload, "lineage_id", fallback=pair_key.lineage_id),
            _required_string(candidate_payload, "instance_id", fallback=pair_key.instance_id),
            _positive_int(candidate_payload, "replicate", fallback=pair_key.replicate),
        ),
        arm=_required_string(candidate_payload, "arm", fallback=arm),
        slot_index=_nonnegative_int(candidate_payload, "slot_index"),
        slot_id=_required_string(candidate_payload, "slot_id"),
        proposal_status=_required_string(candidate_payload, "proposal_status"),
        canonical_ast_hash=_optional_string(candidate_payload, "canonical_ast_hash"),
        raw_response_hash=_optional_string(candidate_payload, "raw_response_hash"),
        candidate=candidate_payload.get("candidate"),
        raw_response=_mapping(candidate_payload.get("raw_response", {}), "raw_response"),
    )
    return VerificationOutcome.from_dict(candidate, outcome_payload)


def _ground_truth(value: object) -> str:
    aliases = {"vulnerable": "positive", "mutant": "positive", "patched": "negative", "control": "negative"}
    value = aliases.get(value, value)
    if value not in {"positive", "negative", "unresolved"}:
        raise ValueError("ground_truth must be positive, negative or unresolved")
    return str(value)


def _required_string(value: Mapping[str, Any], field: str, *, fallback: str | None = None) -> str:
    item = value.get(field, fallback)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{field} must be a non-empty string")
    return item


def _optional_string(value: Mapping[str, Any], field: str) -> str | None:
    item = value.get(field)
    if item is not None and (not isinstance(item, str) or not item):
        raise ValueError(f"{field} must be a non-empty string or null")
    return item


def _positive_int(value: Mapping[str, Any], field: str, *, fallback: int | None = None) -> int:
    item = value.get(field, fallback)
    if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return item


def _nonnegative_int(value: Mapping[str, Any], field: str) -> int:
    item = value.get(field)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return item


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prefixes", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--compare", nargs=2, metavar=("LEFT", "RIGHT"), default=None)
    args = parser.parse_args(argv)
    campaigns = load_verification_campaigns(args.input)
    metrics = compute_verification_metrics(
        campaigns,
        prefixes=tuple(args.prefixes),
        paired_contrasts=(tuple(args.compare),) if args.compare else (),
    )
    report = metrics.as_dict()
    report["input_path"] = str(args.input)
    report["input_campaigns"] = len(campaigns)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_name(f".{args.out.name}.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.out)
    print(json.dumps({"campaigns": len(campaigns), "groups": len(metrics.groups), "input_hash": metrics.input_hash}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
