"""Owner-accepted support-matrix contract for native and conditioned tools.

The matrix is an eligibility record, not a claim that a tool succeeded on an
instance. It keeps unsupported scope visible and requires evidence before a
matrix can be marked owner-accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable, Mapping

from ..contracts.canonical import sha256_hex


class SupportStatus(StrEnum):
    SUPPORTED = "supported"
    CONDITIONAL = "conditional"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SupportEntry:
    tool: str
    scope: str
    status: SupportStatus
    reason: str
    evidence_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.tool or not self.scope or not self.reason:
            raise ValueError("support entry requires tool, scope and reason")
        if self.evidence_hash is not None and (
            len(self.evidence_hash) != 64
            or self.evidence_hash != self.evidence_hash.lower()
            or any(char not in "0123456789abcdef" for char in self.evidence_hash)
        ):
            raise ValueError("support evidence_hash must be a lowercase SHA-256 hex digest")

    def as_dict(self) -> dict[str, object]:
        return {
            "tool": self.tool,
            "scope": self.scope,
            "status": self.status.value,
            "reason": self.reason,
            "evidence_hash": self.evidence_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "SupportEntry":
        try:
            status = SupportStatus(payload["status"])
            tool = payload["tool"]
            scope = payload["scope"]
            reason = payload["reason"]
        except (KeyError, ValueError, TypeError) as error:
            raise ValueError("invalid support entry") from error
        if not all(isinstance(value, str) for value in (tool, scope, reason)):
            raise ValueError("support entry identity and reason must be strings")
        evidence = payload.get("evidence_hash")
        if evidence is not None and not isinstance(evidence, str):
            raise ValueError("support entry evidence_hash must be a string or null")
        return cls(tool, scope, status, reason, evidence)


@dataclass(frozen=True, slots=True)
class SupportMatrix:
    matrix_id: str
    entries: tuple[SupportEntry, ...]
    acceptance_status: str = "draft"
    acceptance_owner: str | None = None
    accepted_at: str | None = None
    acceptance_agent: str | None = None

    def __post_init__(self) -> None:
        if not self.matrix_id:
            raise ValueError("support matrix identity is required")
        keys = [(entry.tool, entry.scope) for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("support matrix entries must be unique")
        if self.acceptance_status not in {"draft", "owner_accepted"}:
            raise ValueError("acceptance_status must be draft or owner_accepted")
        if self.acceptance_status == "owner_accepted" and (
            not self.acceptance_owner or not self.accepted_at or self.acceptance_agent != "codex"
        ):
            raise ValueError(
                "owner_accepted support matrix requires acceptance_owner, accepted_at and acceptance_agent=codex"
            )
        if self.acceptance_status == "owner_accepted" and any(entry.evidence_hash is None for entry in self.entries):
            raise ValueError("owner-accepted support matrix requires evidence hash for every entry")

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "matrix_id": self.matrix_id,
            "entries": [entry.as_dict() for entry in self.entries],
            "acceptance_status": self.acceptance_status,
            "acceptance_owner": self.acceptance_owner,
            "accepted_at": self.accepted_at,
            "acceptance_agent": self.acceptance_agent,
        }

    @property
    def matrix_hash(self) -> str:
        return sha256_hex(self._payload())

    def as_dict(self) -> dict[str, object]:
        payload = self._payload()
        payload["matrix_hash"] = self.matrix_hash
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "SupportMatrix":
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list):
            raise ValueError("support matrix entries must be a list")
        entries: list[SupportEntry] = []
        for row in raw_entries:
            if not isinstance(row, Mapping):
                raise ValueError("support matrix entry must be an object")
            entries.append(SupportEntry.from_dict(row))
        matrix = cls(
            payload.get("matrix_id") if isinstance(payload.get("matrix_id"), str) else "",
            tuple(entries),
            payload.get("acceptance_status", "draft"),
            payload.get("acceptance_owner") if isinstance(payload.get("acceptance_owner"), str) else None,
            payload.get("accepted_at") if isinstance(payload.get("accepted_at"), str) else None,
            payload.get("acceptance_agent") if isinstance(payload.get("acceptance_agent"), str) else None,
        )
        declared_hash = payload.get("matrix_hash")
        if declared_hash is not None and declared_hash != matrix.matrix_hash:
            raise ValueError("support matrix hash mismatch")
        return matrix

    def entry(self, tool: str, scope: str) -> SupportEntry:
        for candidate in self.entries:
            if candidate.tool == tool and candidate.scope == scope:
                return candidate
        raise KeyError((tool, scope))

    def coverage(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        methods: Iterable[str],
        support_field: str = "supported_methods",
        record_id_field: str = "instance_id",
    ) -> dict[str, object]:
        """Report static operational eligibility without reading outcomes.

        `supported_methods` may be a list of method names or a mapping from
        method name to a boolean. The source record remains untouched, and
        unsupported rows stay in the selected denominator.
        """
        rows = list(records)
        method_names = tuple(dict.fromkeys(methods))
        if any(not isinstance(name, str) or not name for name in method_names):
            raise ValueError("coverage method names must be non-empty strings")
        ids: list[str] = []
        support_sets: dict[str, set[str]] = {}
        for index, row in enumerate(rows, 1):
            identifier = row.get(record_id_field)
            if not isinstance(identifier, str) or not identifier:
                raise ValueError(f"coverage record {index} lacks {record_id_field}")
            if identifier in ids:
                raise ValueError("coverage record IDs must be unique")
            ids.append(identifier)
            raw = row.get(support_field, ())
            if isinstance(raw, Mapping):
                supported = {name for name, value in raw.items() if value is True and isinstance(name, str)}
            elif isinstance(raw, (list, tuple, set, frozenset)):
                supported = {name for name in raw if isinstance(name, str)}
            else:
                raise ValueError(f"coverage record {index} has invalid {support_field}")
            for name in method_names:
                if name in supported:
                    support_sets.setdefault(name, set()).add(identifier)
        selected = set(ids)
        per_method = {
            name: {
                "eligible": len(support_sets.get(name, set())),
                "denominator": len(ids),
                "fraction": len(support_sets.get(name, set())) / len(ids) if ids else None,
                "unsupported": len(ids) - len(support_sets.get(name, set())),
            }
            for name in method_names
        }
        common = set.intersection(*(support_sets.get(name, set()) for name in method_names)) if method_names else set()
        return {
            "record_count": len(ids),
            "methods": per_method,
            "common_supported_record_ids": sorted(common & selected),
            "common_supported_count": len(common & selected),
            "support_field": support_field,
            "outcomes_used": False,
        }


__all__ = ["SupportEntry", "SupportMatrix", "SupportStatus"]
