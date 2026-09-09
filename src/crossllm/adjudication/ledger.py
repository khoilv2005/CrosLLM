"""Method-blinded adjudication records for M09.01-M09.03."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
from pathlib import Path
from typing import Any

from ..contracts.canonical import sha256_hex


class FirstFailure(StrEnum):
    """The prespecified 11-class first-failure taxonomy from the guide."""

    MALFORMED_SERIALIZATION = "malformed_serialization"
    UNRESOLVED_REFERENCE = "unresolved_reference"
    TYPE_DOMAIN_MISMATCH = "type_domain_mismatch"
    UNWARRANTED_PROPERTY = "unwarranted_property"
    VACUITY = "vacuity"
    DUPLICATION = "duplication"
    SOLVER_INFEASIBILITY = "solver_infeasibility"
    TIMEOUT_OR_UNSUPPORTED = "timeout_or_unsupported"
    REPLAY_FAILURE = "replay_failure"
    NON_SECURITY_BEHAVIOR = "non_security_behavior"
    TRUE_VULNERABILITY = "true_vulnerability"


class LabelStatus(StrEnum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"


class MappingStatus(StrEnum):
    MAPPED = "mapped"
    UNMAPPED = "unmapped"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class BlindedFinding:
    """Export-safe finding view; method/backbone identity is intentionally absent."""

    finding_id: str
    instance_id: str
    claim: dict[str, object]
    evidence_hash: str | None = None
    raw_claim_hash: str | None = None
    root_cause_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.finding_id, str) or not self.finding_id or not isinstance(self.instance_id, str) or not self.instance_id:
            raise ValueError("finding_id and instance_id are required")
        if not isinstance(self.claim, dict):
            raise ValueError("claim must be an object")
        leaked = _forbidden_blinded_keys(self.claim)
        if leaked:
            raise ValueError(f"blinded claim contains method identity: {', '.join(leaked)}")

    def as_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "instance_id": self.instance_id,
            "claim": self.claim,
            "evidence_hash": self.evidence_hash,
            "raw_claim_hash": self.raw_claim_hash,
            "root_cause_id": self.root_cause_id,
        }


@dataclass(frozen=True, slots=True)
class Label:
    finding_id: str
    rater_id: str
    role: str
    status: LabelStatus
    first_failure: FirstFailure
    uncertainty_reason: str | None = None
    confidence: str | None = None
    label_version: str = "v1"
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.finding_id or not self.rater_id or not self.role:
            raise ValueError("label finding_id, rater_id and role are required")
        if self.status is LabelStatus.UNRESOLVED and not self.uncertainty_reason:
            raise ValueError("unresolved label requires uncertainty_reason")
        if self.status is LabelStatus.CONFIRMED and self.first_failure is not FirstFailure.TRUE_VULNERABILITY:
            raise ValueError("confirmed label must use true_vulnerability first failure")
        if self.status is not LabelStatus.CONFIRMED and self.first_failure is FirstFailure.TRUE_VULNERABILITY:
            raise ValueError("non-confirmed label cannot use true_vulnerability first failure")

    def as_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "rater_id": self.rater_id,
            "role": self.role,
            "status": self.status.value,
            "first_failure": self.first_failure.value,
            "uncertainty_reason": self.uncertainty_reason,
            "confidence": self.confidence,
            "label_version": self.label_version,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class Reconciliation:
    finding_id: str
    label_ids: tuple[str, ...]
    adjudicator_id: str
    status: LabelStatus
    first_failure: FirstFailure
    reason: str
    uncertainty_reason: str | None = None
    rater_roles: tuple[str, ...] = ()
    role_overlap: bool = False
    label_version: str = "v1"
    created_at: str = ""

    def __post_init__(self) -> None:
        if len(self.label_ids) < 2:
            raise ValueError("reconciliation requires two pre-consensus labels")
        if not self.finding_id or not self.adjudicator_id or not self.reason:
            raise ValueError("reconciliation identity and reason are required")
        if self.status is LabelStatus.UNRESOLVED and not self.uncertainty_reason:
            raise ValueError("unresolved reconciliation requires uncertainty_reason")

    def as_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "label_ids": list(self.label_ids),
            "adjudicator_id": self.adjudicator_id,
            "status": self.status.value,
            "first_failure": self.first_failure.value,
            "reason": self.reason,
            "uncertainty_reason": self.uncertainty_reason,
            "rater_roles": list(self.rater_roles),
            "role_overlap": self.role_overlap,
            "label_version": self.label_version,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class RelabelEvent:
    finding_id: str
    previous_status: LabelStatus
    new_status: LabelStatus
    actor_id: str
    reason: str
    created_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "previous_status": self.previous_status.value,
            "new_status": self.new_status.value,
            "actor_id": self.actor_id,
            "reason": self.reason,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class RequirementMapping:
    finding_id: str
    requirement_id: str | None
    status: MappingStatus
    reviewer_id: str
    reason: str
    created_at: str

    def __post_init__(self) -> None:
        if not self.finding_id or not self.reviewer_id or not self.reason:
            raise ValueError("requirement mapping identity and reason are required")
        if self.status is MappingStatus.MAPPED and not self.requirement_id:
            raise ValueError("mapped requirement requires requirement_id")
        if self.status is not MappingStatus.MAPPED and self.requirement_id is not None:
            raise ValueError("unmapped or uncertain requirement cannot carry requirement_id")


class AdjudicationLedger:
    """In-memory ledger that prevents method leakage and label overwrites."""

    def __init__(self, findings: list[BlindedFinding] | tuple[BlindedFinding, ...]) -> None:
        if len({finding.finding_id for finding in findings}) != len(findings):
            raise ValueError("finding IDs must be unique")
        self._findings = {finding.finding_id: finding for finding in findings}
        self._labels: dict[tuple[str, str], Label] = {}
        self._reconciliations: dict[str, Reconciliation] = {}
        self._effective_status: dict[str, LabelStatus] = {}
        self._relabels: list[RelabelEvent] = []
        self._mappings: dict[str, RequirementMapping] = {}

    @property
    def findings(self) -> tuple[BlindedFinding, ...]:
        return tuple(self._findings.values())

    @property
    def labels(self) -> tuple[Label, ...]:
        return tuple(self._labels.values())

    @property
    def reconciliations(self) -> tuple[Reconciliation, ...]:
        return tuple(self._reconciliations.values())

    @property
    def relabel_history(self) -> tuple[RelabelEvent, ...]:
        return tuple(self._relabels)

    @property
    def requirement_mappings(self) -> tuple[RequirementMapping, ...]:
        return tuple(self._mappings.values())

    def export_blinded(self) -> dict[str, object]:
        """Return only fields permissible before labels/consensus exist."""
        payload = {
            "schema_version": 1,
            "export_id": sha256_hex([finding.as_dict() for finding in self.findings]),
            "findings": [finding.as_dict() for finding in self.findings],
            "method_identity_included": False,
        }
        return payload

    def export_labels(self) -> dict[str, object]:
        """Export labels without adding any method/backbone identity."""
        return {
            "schema_version": 1,
            "finding_export_id": self.export_blinded()["export_id"],
            "labels": [label.as_dict() for label in self.labels],
            "method_identity_included": False,
        }

    def write_blinded(self, path: Path) -> None:
        _write_json(path, self.export_blinded())

    def write_labels(self, path: Path) -> None:
        _write_json(path, self.export_labels())

    def write_json(self, path: Path) -> None:
        _write_json(path, self.as_dict())

    @classmethod
    def from_blinded(cls, payload: dict[str, object]) -> "AdjudicationLedger":
        """Import an export-safe finding package and reject identity leakage."""
        if payload.get("schema_version") != 1 or payload.get("method_identity_included") is not False:
            raise ValueError("invalid blinded finding export contract")
        rows = payload.get("findings")
        if not isinstance(rows, list):
            raise ValueError("blinded finding export requires a findings array")
        findings: list[BlindedFinding] = []
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                raise ValueError(f"blinded finding {index} must be an object")
            forbidden = _forbidden_blinded_keys(row)
            if forbidden:
                raise ValueError(f"blinded finding contains forbidden fields: {', '.join(forbidden)}")
            try:
                findings.append(BlindedFinding(
                    finding_id=_required_string(row, "finding_id"),
                    instance_id=_required_string(row, "instance_id"),
                    claim=_required_object(row, "claim"),
                    evidence_hash=_optional_string(row, "evidence_hash"),
                    raw_claim_hash=_optional_string(row, "raw_claim_hash"),
                    root_cause_id=_optional_string(row, "root_cause_id"),
                ))
            except (TypeError, ValueError) as error:
                raise ValueError(f"invalid blinded finding {index}: {error}") from error
        expected_export_id = sha256_hex([finding.as_dict() for finding in findings])
        if payload.get("export_id") != expected_export_id:
            raise ValueError("blinded finding export hash mismatch")
        return cls(findings)

    def import_labels(self, payload: dict[str, object]) -> None:
        """Import pre-consensus labels exactly once, preserving their roles."""
        if payload.get("schema_version") != 1 or payload.get("method_identity_included") is not False:
            raise ValueError("invalid label export contract")
        expected = self.export_blinded()["export_id"]
        if payload.get("finding_export_id") != expected:
            raise ValueError("labels refer to a different blinded finding export")
        rows = payload.get("labels")
        if not isinstance(rows, list):
            raise ValueError("label export requires a labels array")
        for index, row in enumerate(rows, 1):
            try:
                if not isinstance(row, dict):
                    raise ValueError("label must be an object")
                self.add_label(_label_from_dict(row))
            except (TypeError, ValueError, KeyError) as error:
                raise ValueError(f"invalid label {index}: {error}") from error

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "AdjudicationLedger":
        """Restore a complete ledger while reapplying all write invariants."""
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported adjudication ledger schema")
        supplied_hash = payload.get("ledger_hash")
        if not isinstance(supplied_hash, str):
            raise ValueError("ledger ledger_hash is required")
        unsigned_payload = {key: value for key, value in payload.items() if key != "ledger_hash"}
        if supplied_hash != sha256_hex(unsigned_payload):
            raise ValueError("ledger hash mismatch")
        findings_payload = {
            "schema_version": 1,
            "export_id": sha256_hex(payload.get("findings", [])),
            "findings": payload.get("findings", []),
            "method_identity_included": False,
        }
        ledger = cls.from_blinded(findings_payload)
        labels = payload.get("labels", [])
        if not isinstance(labels, list):
            raise ValueError("ledger labels must be an array")
        for row in labels:
            if not isinstance(row, dict):
                raise ValueError("ledger label must be an object")
            ledger.add_label(_label_from_dict(row))
        reconciliations = payload.get("reconciliations", [])
        if not isinstance(reconciliations, list):
            raise ValueError("ledger reconciliations must be an array")
        for row in reconciliations:
            if not isinstance(row, dict):
                raise ValueError("ledger reconciliation must be an object")
            finding_id = _required_string(row, "finding_id")
            restored = ledger.reconcile(
                finding_id,
                adjudicator_id=_required_string(row, "adjudicator_id"),
                reason=_required_string(row, "reason"),
                uncertainty_reason=_optional_string(row, "uncertainty_reason"),
                created_at=_required_string(row, "created_at"),
            )
            expected_reconciliation = restored.as_dict()
            # Accept v1 ledgers written before role-overlap fields existed,
            # while always emitting the enriched representation on rewrite.
            for legacy_field in ("rater_roles", "role_overlap"):
                if legacy_field not in row:
                    expected_reconciliation.pop(legacy_field, None)
            if expected_reconciliation != row:
                raise ValueError(f"reconciliation invariant/hash mismatch for {finding_id}")
        relabels = payload.get("relabel_history", [])
        if not isinstance(relabels, list):
            raise ValueError("ledger relabel_history must be an array")
        for row in relabels:
            if not isinstance(row, dict):
                raise ValueError("ledger relabel event must be an object")
            event = ledger.relabel(
                _required_string(row, "finding_id"),
                LabelStatus(_required_string(row, "new_status")),
                actor_id=_required_string(row, "actor_id"),
                reason=_required_string(row, "reason"),
                created_at=_required_string(row, "created_at"),
            )
            if event.as_dict() != row:
                raise ValueError("relabel history mismatch")
        mappings = payload.get("requirement_mappings", [])
        if not isinstance(mappings, list):
            raise ValueError("ledger requirement_mappings must be an array")
        for row in mappings:
            if not isinstance(row, dict):
                raise ValueError("requirement mapping must be an object")
            ledger.map_requirement(RequirementMapping(
                _required_string(row, "finding_id"),
                _optional_string(row, "requirement_id"),
                MappingStatus(_required_string(row, "status")),
                _required_string(row, "reviewer_id"),
                _required_string(row, "reason"),
                _required_string(row, "created_at"),
            ))
        return ledger

    @classmethod
    def load_json(cls, path: Path) -> "AdjudicationLedger":
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"cannot read adjudication ledger: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError("adjudication ledger must be an object")
        return cls.from_dict(payload)

    def add_label(self, label: Label) -> None:
        if label.finding_id not in self._findings:
            raise KeyError("label references unknown finding")
        key = (label.finding_id, label.rater_id)
        if key in self._labels:
            raise ValueError("rater cannot overwrite a pre-consensus label")
        self._labels[key] = label

    def reconcile(
        self,
        finding_id: str,
        *,
        adjudicator_id: str,
        reason: str,
        uncertainty_reason: str | None = None,
        created_at: str | None = None,
    ) -> Reconciliation:
        if finding_id not in self._findings:
            raise KeyError("unknown finding")
        labels = [label for label in self._labels.values() if label.finding_id == finding_id]
        if len(labels) != 2:
            raise ValueError("exactly two independent labels are required")
        if len({label.rater_id for label in labels}) != len(labels):
            raise ValueError("labels must come from distinct raters")
        if any(label.rater_id == adjudicator_id for label in labels):
            raise ValueError("adjudicator must be independent of raters")
        if finding_id in self._reconciliations:
            raise ValueError("finding already reconciled")
        first = labels[0]
        if all(label.status is first.status and label.first_failure is first.first_failure for label in labels):
            status = first.status
            failure = first.first_failure
        else:
            status = LabelStatus.UNRESOLVED
            failure = FirstFailure.TIMEOUT_OR_UNSUPPORTED
            if not uncertainty_reason:
                raise ValueError("disagreement requires uncertainty_reason")
        reconciliation = Reconciliation(
            finding_id=finding_id,
            label_ids=tuple(f"{label.rater_id}:{label.finding_id}" for label in labels),
            adjudicator_id=adjudicator_id,
            status=status,
            first_failure=failure,
            reason=reason,
            uncertainty_reason=uncertainty_reason,
            rater_roles=tuple(label.role for label in labels),
            role_overlap=len({label.role for label in labels}) != len(labels),
            label_version="v1",
            created_at=created_at or datetime.now(timezone.utc).isoformat(),
        )
        self._reconciliations[finding_id] = reconciliation
        self._effective_status[finding_id] = status
        return reconciliation

    def relabel(self, finding_id: str, new_status: LabelStatus, *, actor_id: str, reason: str, created_at: str | None = None) -> RelabelEvent:
        current = self._reconciliations.get(finding_id)
        if current is None:
            raise ValueError("only a reconciled finding can be relabeled")
        if not actor_id or not reason:
            raise ValueError("relabel requires actor and reason")
        event = RelabelEvent(
            finding_id,
            self._effective_status.get(finding_id, current.status),
            new_status,
            actor_id,
            reason,
            created_at or datetime.now(timezone.utc).isoformat(),
        )
        self._relabels.append(event)
        self._effective_status[finding_id] = new_status
        return event

    def map_requirement(self, mapping: RequirementMapping) -> None:
        if mapping.finding_id not in self._findings:
            raise KeyError("mapping references unknown finding")
        if mapping.finding_id in self._mappings:
            raise ValueError("finding already has a requirement mapping")
        self._mappings[mapping.finding_id] = mapping

    def deduplicated_finding_ids(self) -> tuple[str, ...]:
        """Return one finding per available instance/root-cause key."""
        seen: set[tuple[str, str]] = set()
        result: list[str] = []
        for finding in self.findings:
            key = (finding.instance_id, finding.root_cause_id or finding.finding_id)
            if key in seen:
                continue
            seen.add(key)
            result.append(finding.finding_id)
        return tuple(result)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "findings": [finding.as_dict() for finding in self.findings],
            "labels": [label.as_dict() for label in self.labels],
            "reconciliations": [item.as_dict() for item in self.reconciliations],
            "relabel_history": [item.as_dict() for item in self.relabel_history],
            "requirement_mappings": [mapping.__dict__ if hasattr(mapping, "__dict__") else {
                "finding_id": mapping.finding_id,
                "requirement_id": mapping.requirement_id,
                "status": mapping.status.value,
                "reviewer_id": mapping.reviewer_id,
                "reason": mapping.reason,
                "created_at": mapping.created_at,
            } for mapping in self.requirement_mappings],
        }
        return {**payload, "ledger_hash": sha256_hex(payload)}


def _forbidden_blinded_keys(value: object) -> tuple[str, ...]:
    forbidden_names = {
        "method", "method_id", "track", "backbone", "model", "model_tag",
        "provider", "checkpoint", "served_weight_digest",
    }
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.lower() in forbidden_names:
                found.add(key)
            found.update(_forbidden_blinded_keys(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.update(_forbidden_blinded_keys(child))
    return tuple(sorted(found))


def _required_string(row: dict[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _optional_string(row: dict[str, object], field: str) -> str | None:
    value = row.get(field)
    if value is not None and (not isinstance(value, str) or not value):
        raise ValueError(f"{field} must be a non-empty string or null")
    return value


def _required_object(row: dict[str, object], field: str) -> dict[str, object]:
    value = row.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _label_from_dict(row: dict[str, object]) -> Label:
    return Label(
        _required_string(row, "finding_id"),
        _required_string(row, "rater_id"),
        _required_string(row, "role"),
        LabelStatus(_required_string(row, "status")),
        FirstFailure(_required_string(row, "first_failure")),
        _optional_string(row, "uncertainty_reason"),
        _optional_string(row, "confidence"),
        _required_string(row, "label_version"),
        _required_string(row, "created_at"),
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
