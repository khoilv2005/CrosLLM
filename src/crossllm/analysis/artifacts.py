"""Deterministic analysis artifact construction from frozen campaign JSONL."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..contracts.canonical import sha256_hex
from .estimands import AnalysisReport, CampaignOutcome, OutcomeAvailability, analyze_outcomes
from .reporting import ContrastInference, analyze_contrast_family
from .tables import AnalysisTable, build_analysis_tables


class AnalysisInputError(ValueError):
    """A raw campaign row cannot be admitted to analysis."""


PRIMARY_CONTRAST_COUNT = 5
SECONDARY_CONTRAST_COUNT = 6


@dataclass(frozen=True, slots=True)
class AnalysisArtifact:
    input_hash: str
    row_count: int
    report: AnalysisReport
    primary_inference: tuple[ContrastInference, ...]
    secondary_inference: tuple[ContrastInference, ...]
    artifact_hash: str

    @property
    def tables(self) -> tuple[AnalysisTable, ...]:
        return build_analysis_tables(self.report, self.primary_inference, self.secondary_inference)

    def as_dict(self) -> dict[str, object]:
        payload = {
            "schema_version": 1,
            "input_hash": self.input_hash,
            "row_count": self.row_count,
            "analysis": self.report.as_dict(),
            "primary_inference": [item.as_dict() for item in self.primary_inference],
            "secondary_inference": [item.as_dict() for item in self.secondary_inference],
            "tables": [table.as_dict() for table in self.tables],
        }
        return {**payload, "artifact_hash": self.artifact_hash}

    def write_json(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), sort_keys=True, indent=2) + "\n", encoding="utf-8")

    def write_bundle(self, directory: Path) -> Path:
        """Write analysis JSON, all table CSVs and a provenance manifest."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        analysis_path = directory / "analysis.json"
        self.write_json(analysis_path)
        table_rows: list[dict[str, object]] = []
        for table in self.tables:
            path = table.write_csv(directory)
            content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            table_rows.append({
                "table_id": table.table_id,
                "path": path.name,
                "sha256": content_hash,
                "row_count": len(table.rows),
            })
        payload = {
            "schema_version": 1,
            "input_hash": self.input_hash,
            "artifact_hash": self.artifact_hash,
            "row_count": self.row_count,
            "analysis_json": analysis_path.name,
            "tables": table_rows,
        }
        manifest = directory / "manifest.json"
        manifest.write_text(
            json.dumps({**payload, "bundle_hash": sha256_hex(payload)}, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest


def write_analysis_bundle(artifact: AnalysisArtifact, directory: Path) -> Path:
    """Functional wrapper for callers that do not retain an artifact method."""
    return artifact.write_bundle(directory)


class AnalysisArtifactBuilder:
    """Build a reproducible artifact without changing denominators or labels."""

    def build(
        self,
        rows: Iterable[Mapping[str, Any] | CampaignOutcome],
        *,
        primary_contrasts: Mapping[str, Mapping[str, float]] | None = None,
        secondary_contrasts: Mapping[str, Mapping[str, float]] | None = None,
        draws: int = 10_000,
        seed: int = 0,
        require_prespecified_families: bool = False,
    ) -> AnalysisArtifact:
        outcomes = tuple(row if isinstance(row, CampaignOutcome) else campaign_outcome_from_dict(row) for row in rows)
        canonical_rows = [_outcome_dict(row) for row in sorted(outcomes, key=_outcome_sort_key)]
        input_hash = sha256_hex(canonical_rows)
        report = analyze_outcomes(outcomes)
        primary_values = dict(primary_contrasts or {})
        secondary_values = dict(secondary_contrasts or {})
        if require_prespecified_families:
            if len(primary_values) != PRIMARY_CONTRAST_COUNT:
                raise AnalysisInputError(
                    f"primary contrast family requires exactly {PRIMARY_CONTRAST_COUNT} contrasts"
                )
            if len(secondary_values) != SECONDARY_CONTRAST_COUNT:
                raise AnalysisInputError(
                    f"secondary contrast family requires exactly {SECONDARY_CONTRAST_COUNT} contrasts"
                )
        primary = analyze_contrast_family(primary_values, draws=draws, seed=seed)
        secondary = analyze_contrast_family(secondary_values, draws=draws, seed=seed + len(primary))
        payload = {
            "schema_version": 1,
            "input_hash": input_hash,
            "row_count": len(outcomes),
            "analysis": report.as_dict(),
            "primary_inference": [item.as_dict() for item in primary],
            "secondary_inference": [item.as_dict() for item in secondary],
            "tables": [table.as_dict() for table in build_analysis_tables(report, primary, secondary)],
        }
        return AnalysisArtifact(input_hash, len(outcomes), report, primary, secondary, sha256_hex(payload))


def load_campaign_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    """Load strict JSONL rows; blank lines are ignored, malformed rows reject."""
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as error:
        raise AnalysisInputError(f"cannot read raw campaign file: {error}") from error
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise AnalysisInputError(f"line {line_number}: malformed JSON: {error.msg}") from error
        if not isinstance(row, dict):
            raise AnalysisInputError(f"line {line_number}: campaign outcome must be an object")
        rows.append(row)
    return tuple(rows)


def campaign_outcome_from_dict(row: Mapping[str, Any]) -> CampaignOutcome:
    """Decode a raw row while preserving omitted optional measurements as null."""
    required = ("campaign_id", "instance_id", "lineage_id", "method", "replicate", "ground_truth")
    missing = tuple(field for field in required if field not in row)
    if missing:
        raise AnalysisInputError(f"campaign outcome missing fields: {', '.join(missing)}")
    try:
        availability = OutcomeAvailability(row.get("availability", OutcomeAvailability.AVAILABLE.value))
        return CampaignOutcome(
            campaign_id=_string(row, "campaign_id"),
            instance_id=_string(row, "instance_id"),
            lineage_id=_string(row, "lineage_id"),
            method=_string(row, "method"),
            replicate=_positive_int(row, "replicate"),
            ground_truth=_string(row, "ground_truth"),
            detected=_optional_bool(row, "detected"),
            useful_proposal=_optional_bool(row, "useful_proposal"),
            claim_emitted=_optional_bool(row, "claim_emitted"),
            correct_claim=_optional_bool(row, "correct_claim"),
            native_witness=_optional_bool(row, "native_witness"),
            independent_replay=_optional_bool(row, "independent_replay"),
            claim_time_seconds=_optional_number(row, "claim_time_seconds"),
            witness_time_seconds=_optional_number(row, "witness_time_seconds"),
            horizon_seconds=_number(row, "horizon_seconds", 1.0),
            availability=availability,
            first_failure=_optional_string(row, "first_failure"),
        )
    except (TypeError, ValueError) as error:
        raise AnalysisInputError(str(error)) from error


def _outcome_sort_key(row: CampaignOutcome) -> tuple[str, str, str, int, str]:
    return (row.lineage_id, row.instance_id, row.method, row.replicate, row.campaign_id)


def _outcome_dict(row: CampaignOutcome) -> dict[str, object]:
    return {
        "campaign_id": row.campaign_id,
        "instance_id": row.instance_id,
        "lineage_id": row.lineage_id,
        "method": row.method,
        "replicate": row.replicate,
        "ground_truth": row.ground_truth,
        "detected": row.detected,
        "useful_proposal": row.useful_proposal,
        "claim_emitted": row.claim_emitted,
        "correct_claim": row.correct_claim,
        "native_witness": row.native_witness,
        "independent_replay": row.independent_replay,
        "claim_time_seconds": row.claim_time_seconds,
        "witness_time_seconds": row.witness_time_seconds,
        "horizon_seconds": row.horizon_seconds,
        "availability": row.availability.value,
        "first_failure": row.first_failure,
    }


def _string(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str):
        raise AnalysisInputError(f"{field} must be a string")
    return value


def _optional_string(row: Mapping[str, Any], field: str) -> str | None:
    value = row.get(field)
    if value is not None and not isinstance(value, str):
        raise AnalysisInputError(f"{field} must be a string or null")
    return value


def _positive_int(row: Mapping[str, Any], field: str) -> int:
    value = row.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AnalysisInputError(f"{field} must be a positive integer")
    return value


def _optional_bool(row: Mapping[str, Any], field: str) -> bool | None:
    value = row.get(field)
    if value is not None and not isinstance(value, bool):
        raise AnalysisInputError(f"{field} must be boolean or null")
    return value


def _optional_number(row: Mapping[str, Any], field: str) -> float | None:
    value = row.get(field)
    if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise AnalysisInputError(f"{field} must be numeric or null")
    return float(value) if value is not None else None


def _number(row: Mapping[str, Any], field: str, default: float) -> float:
    value = row.get(field, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise AnalysisInputError(f"{field} must be numeric")
    return float(value)
