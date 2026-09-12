#!/usr/bin/env python3
"""Run the shared verification stage over proposal archives.

This runner is intentionally provider-free.  It loads immutable proposal
archives, builds public runtime bindings, and sends every slot through the same
``SharedVerificationPipeline``.  Actual symbolic, witness and independent
replay executors are injected by the runtime integration; when they are not
configured their stages remain ``unsupported`` rather than becoming a false
negative or a verified finding.
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

from crossllm.verification import (
    ArchiveRoot,
    CampaignAvailability,
    CandidateInput,
    FileVerificationCache,
    StageResult,
    StageStatus,
    VerificationOutcome,
    verify_candidates,
    load_archives,
    public_xlir_symbols,
    load_case_runtime,
    summarize_campaign_archive_timing,
    SourceBackedVerificationExecutors,
    SourceCommandSpec,
    VerificationExecutors,
)
from crossllm.replay import EVMReplaySpec


def load_public_manifest(path: Path) -> dict[str, dict[str, object]]:
    """Load only public case identity/truth metadata for campaign grouping."""

    result: dict[str, dict[str, object]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: malformed JSON: {error.msg}") from error
        if not isinstance(row, dict) or not isinstance(row.get("instance_id"), str):
            raise ValueError(f"{path}:{line_number}: manifest row has no instance_id")
        result[row["instance_id"]] = row
    return result


def parse_archive_roots(values: list[str]) -> tuple[ArchiveRoot, ...]:
    roots: list[ArchiveRoot] = []
    for value in values:
        arm, separator, raw_path = value.partition("=")
        if not separator or not arm or not raw_path:
            raise ValueError(f"archive root must use ARM=PATH, got {value!r}")
        roots.append(ArchiveRoot(arm, Path(raw_path)))
    return tuple(roots)


def run_archives(
    repo_root: Path,
    roots: tuple[ArchiveRoot, ...],
    manifest: Mapping[str, Mapping[str, object]],
    *,
    expected_slots: int = 8,
    cache: FileVerificationCache | None = None,
    executors: VerificationExecutors | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    dataset = load_archives(roots, expected_slots=expected_slots)
    output: list[dict[str, object]] = []
    availability_counts: dict[str, int] = {}
    verified_count = 0
    outcome_count = 0
    case_cache: dict[tuple[str, str], tuple[object, list[Any]] | Exception] = {}
    for archive in dataset.campaigns:
        case_id = archive.pair_key.instance_id
        manifest_row = manifest.get(case_id)
        if manifest_row is None:
            raise ValueError(f"{archive.archive_path}: instance {case_id!r} is absent from public manifest")
        truth = normalize_ground_truth(manifest_row.get("status"))
        property_family = str(manifest_row.get("property_family", "unknown"))
        case_key = (archive.pair_key.lineage_id, case_id)
        cached_case = case_cache.get(case_key)
        if cached_case is None:
            try:
                case = load_case_runtime(repo_root, archive.pair_key.lineage_id, case_id)
                symbols = public_xlir_symbols(repo_root, archive.pair_key.lineage_id)
                cached_case = (case, symbols)
            except Exception as error:  # case-level failure is retained per slot
                cached_case = error
            case_cache[case_key] = cached_case
        candidates = archive.candidate_inputs()
        outcomes: tuple[VerificationOutcome, ...]
        if isinstance(cached_case, Exception):
            outcomes = tuple(
                unavailable_outcome(item, "runtime_case_load_failure", cached_case)
                for item in candidates
            )
        else:
            case, symbols = cached_case
            outcomes = verify_candidates(candidates, case, symbols, cache=cache, executors=executors)
        outcome_count += len(outcomes)
        verified_count += sum(outcome.verified_finding is True for outcome in outcomes)
        availability, reason = classify_campaign_availability(archive, outcomes, cached_case)
        availability_counts[availability.value] = availability_counts.get(availability.value, 0) + 1
        output.append(campaign_envelope(archive, truth, property_family, availability, reason, outcomes))
    summary = {
        "schema_version": 1,
        "record_type": "verification_stage_summary",
        "campaigns": len(output),
        "outcomes": outcome_count,
        "verified_findings": verified_count,
        "availability": dict(sorted(availability_counts.items())),
        "provider_calls": 0,
        "gold_fields_read": False,
        "mode": "shared_pipeline_without_provider_calls",
        "executor_mode": "shared_pipeline_without_provider_calls" if executors is None else "source_backed_json_protocol",
    }
    return output, summary


def campaign_envelope(
    archive: Any,
    ground_truth: str,
    property_family: str,
    availability: CampaignAvailability,
    missing_reason: str | None,
    outcomes: list[VerificationOutcome],
) -> dict[str, object]:
    row: dict[str, object] = {
        "schema_version": 1,
        "record_type": "verification_campaign",
        "campaign_id": archive.campaign_id,
        "attempt_id": archive.attempt_id,
        "arm": archive.arm,
        "method": archive.method,
        "backbone": archive.backbone,
        "model_tag": archive.model_tag,
        "lineage_id": archive.pair_key.lineage_id,
        "instance_id": archive.pair_key.instance_id,
        "replicate": archive.pair_key.replicate,
        "ground_truth": ground_truth,
        "property_family": property_family,
        "slot_count": archive.slot_count,
        "availability": availability.value,
        "missing_reason": missing_reason,
        "archive_path": archive.archive_path,
        "outcomes": [_outcome_envelope(outcome) for outcome in outcomes],
    }
    raw_row = getattr(archive, "raw_row", None)
    if isinstance(raw_row, Mapping):
        try:
            row["timing"] = summarize_campaign_archive_timing(archive, outcomes).as_dict()
        except (TypeError, ValueError, KeyError) as error:
            # Preserve an explicit unavailable observation rather than making
            # an absent/malformed provider receipt look like zero cost/time.
            row["timing"] = {
                "schema_version": 1,
                "record_type": "method_timing_unavailable",
                "status": "unavailable",
                "reason": f"timing_projection_failure:{type(error).__name__}:{error}",
            }
    return row


def _outcome_envelope(outcome: VerificationOutcome) -> dict[str, object]:
    candidate = outcome.candidate
    return {
        "candidate": {
            "campaign_id": candidate.campaign_id,
            "attempt_id": candidate.attempt_id,
            "lineage_id": candidate.pair_key.lineage_id,
            "instance_id": candidate.pair_key.instance_id,
            "replicate": candidate.pair_key.replicate,
            "arm": candidate.arm,
            "slot_index": candidate.slot_index,
            "slot_id": candidate.slot_id,
            "proposal_status": candidate.proposal_status,
            "canonical_ast_hash": candidate.canonical_ast_hash,
            "raw_response_hash": candidate.raw_response_hash,
            "candidate": candidate.candidate,
            "raw_response": dict(candidate.raw_response),
        },
        "outcome": outcome.as_dict(),
    }


def unavailable_outcome(candidate: CandidateInput, reason: str, error: Exception | None = None) -> VerificationOutcome:
    detail = reason if error is None else f"{reason}:{type(error).__name__}:{error}"
    grounding = (
        StageResult("grounding", StageStatus.NOT_APPLICABLE, "proposal_abstained")
        if candidate.proposal_status != "candidate"
        else StageResult("grounding", StageStatus.UNSUPPORTED, detail)
    )
    return VerificationOutcome(
        candidate=candidate,
        stages=(
            grounding,
            StageResult("symbolic_search", StageStatus.NOT_APPLICABLE, "grounding_not_passed"),
            StageResult("witness_check", StageStatus.NOT_APPLICABLE, "grounding_not_passed"),
            StageResult("independent_replay", StageStatus.NOT_APPLICABLE, "grounding_not_passed"),
        ),
        first_failure="grounding" if candidate.proposal_status == "candidate" else None,
    )


def classify_campaign_availability(
    archive: Any,
    outcomes: list[VerificationOutcome],
    case_context: object,
) -> tuple[CampaignAvailability, str | None]:
    if isinstance(case_context, Exception):
        return CampaignAvailability.UNSUPPORTED, "runtime_case_load_failure"
    if archive.provider_failure_count:
        return CampaignAvailability.UNKNOWN, "provider_failure_or_partial_archive"
    statuses = {stage.status for outcome in outcomes for stage in outcome.stages}
    if StageStatus.CRASH in statuses:
        return CampaignAvailability.UNKNOWN, "verification_stage_crash"
    if StageStatus.TIMEOUT in statuses or StageStatus.UNKNOWN in statuses:
        return CampaignAvailability.UNKNOWN, "verification_stage_incomplete"
    if StageStatus.UNSUPPORTED in statuses:
        return CampaignAvailability.UNSUPPORTED, "runtime_or_backend_unsupported"
    return CampaignAvailability.AVAILABLE, None


def normalize_ground_truth(value: object) -> str:
    aliases = {
        "vulnerable": "positive",
        "mutant": "positive",
        "sealed_positive": "positive",
        "patched": "negative",
        "control": "negative",
        "benign_negative": "negative",
    }
    normalized = aliases.get(value, value)
    if normalized not in {"positive", "negative", "unresolved"}:
        raise ValueError(f"unsupported public ground truth {value!r}")
    return str(normalized)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    temporary.replace(path)


def load_source_executors(
    path: Path,
    *,
    repo_root: Path | None = None,
) -> SourceBackedVerificationExecutors:
    """Load a pinned source-executor configuration without shell expansion."""

    config_path = Path(path).resolve()
    payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValueError("source executor config must be an object")
    base = config_path.parent
    search = _source_command(payload.get("search"), base, "search")
    witness = _source_command(payload.get("witness"), base, "witness")
    raw_replay = payload.get("replay")
    if not isinstance(raw_replay, Mapping):
        raise ValueError("source executor config replay must be an object")
    replay_workdir = _config_path(raw_replay.get("workdir"), base, "replay.workdir")
    replay = EVMReplaySpec(
        adapter_id=_required_string(raw_replay, "adapter_id", "replay"),
        executable=_required_string(raw_replay, "executable", "replay"),
        arguments=_arguments(raw_replay, "replay"),
        tool_revision=_required_string(raw_replay, "tool_revision", "replay"),
        container_ref=_required_string(raw_replay, "container_ref", "replay"),
        artifact_hash=_required_string(raw_replay, "artifact_hash", "replay"),
        initialization_hash=_required_string(raw_replay, "initialization_hash", "replay"),
        profile_hash=_required_string(raw_replay, "profile_hash", "replay"),
        semantic_engine=_required_string(raw_replay, "semantic_engine", "replay"),
        timeout_seconds=_number(raw_replay.get("timeout_seconds", 180.0), "replay.timeout_seconds"),
        support_matrix_hash=raw_replay.get("support_matrix_hash") if isinstance(raw_replay.get("support_matrix_hash"), str) else None,
    )
    return SourceBackedVerificationExecutors(
        search=search,
        witness=witness,
        replay=replay,
        replay_workdir=replay_workdir,
        repo_root=repo_root,
        allow_dynamic_harness_bindings=(
            payload.get("allow_dynamic_harness_bindings") is True
        ),
    )


def _source_command(value: object, base: Path, label: str) -> SourceCommandSpec:
    if not isinstance(value, Mapping):
        raise ValueError(f"source executor config {label} must be an object")
    return SourceCommandSpec(
        adapter_id=_required_string(value, "adapter_id", label),
        executable=_required_string(value, "executable", label),
        arguments=_arguments(value, label),
        workdir=_config_path(value.get("workdir"), base, f"{label}.workdir"),
        tool_revision=_required_string(value, "tool_revision", label),
        container_ref=_required_string(value, "container_ref", label),
        timeout_seconds=_number(value.get("timeout_seconds", 180.0), f"{label}.timeout_seconds"),
    )


def _arguments(value: Mapping[str, object], label: str) -> tuple[str, ...]:
    arguments = value.get("arguments")
    if not isinstance(arguments, list) or any(not isinstance(argument, str) for argument in arguments):
        raise ValueError(f"{label}.arguments must be a list of strings")
    return tuple(arguments)


def _config_path(value: object, base: Path, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty path")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = base / candidate
    candidate = candidate.resolve()
    if not candidate.is_dir():
        raise ValueError(f"{label} must be an existing directory")
    return candidate


def _required_string(value: Mapping[str, object], field: str, label: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{label}.{field} must be a non-empty string")
    return item


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{label} must be positive")
    return float(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--archive-root", action="append", required=True, metavar="ARM=PATH")
    parser.add_argument("--manifest", type=Path, default=ROOT / "dataset" / "benchmark" / "benchmark.public.jsonl")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--expected-slots", type=int, default=8)
    parser.add_argument("--source-executors", type=Path, default=None, help="optional pinned source symbolic/witness/replay executor config")
    args = parser.parse_args(argv)
    roots = parse_archive_roots(args.archive_root)
    manifest = load_public_manifest(args.manifest)
    cache = FileVerificationCache(args.cache) if args.cache is not None else None
    source_executors = (
        load_source_executors(args.source_executors, repo_root=args.repo_root)
        if args.source_executors is not None else None
    )
    try:
        rows, summary = run_archives(
            args.repo_root,
            roots,
            manifest,
            expected_slots=args.expected_slots,
            cache=cache,
            executors=source_executors.executors() if source_executors is not None else None,
        )
    finally:
        if source_executors is not None:
            source_executors.close()
    write_jsonl(args.out, rows)
    summary_path = args.out.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
