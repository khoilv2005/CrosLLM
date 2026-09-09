"""Owner-accepted support scope for independent EVM replay."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from ..contracts.canonical import sha256_hex


class SupportStatus(StrEnum):
    SUPPORTED = "supported"
    CONDITIONAL = "conditional"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SupportEntry:
    category: str
    feature: str
    status: SupportStatus
    condition: str | None = None
    evidence_hash: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.category not in {"opcode", "precompile", "proxy", "crypto"}:
            raise ValueError("support category must be opcode/precompile/proxy/crypto")
        if not self.feature.strip():
            raise ValueError("support feature must be non-empty")
        if not isinstance(self.status, SupportStatus):
            raise ValueError("support status must be a SupportStatus")
        if self.status is SupportStatus.CONDITIONAL and not self.condition:
            raise ValueError("conditional support requires a condition")
        if self.evidence_hash is not None and not _is_sha256(self.evidence_hash):
            raise ValueError("support evidence_hash must be a lowercase SHA-256 hex digest")

    def as_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "feature": self.feature,
            "status": self.status.value,
            "condition": self.condition,
            "evidence_hash": self.evidence_hash,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class EVMExecutionSupportMatrix:
    matrix_id: str
    engine: str
    engine_revision: str
    entries: tuple[SupportEntry, ...]
    acceptance_status: str = "draft"
    acceptance_owner: str | None = None
    accepted_at: str | None = None
    acceptance_agent: str | None = None

    def __post_init__(self) -> None:
        if not self.matrix_id or not self.engine or not self.engine_revision:
            raise ValueError("support matrix identity is required")
        if self.acceptance_status not in {"draft", "owner_accepted"}:
            raise ValueError("acceptance_status must be draft or owner_accepted")
        if self.acceptance_status == "owner_accepted" and (
            not self.acceptance_owner or not self.accepted_at or self.acceptance_agent != "codex"
        ):
            raise ValueError(
                "owner_accepted support matrix requires acceptance_owner, accepted_at and acceptance_agent=codex"
            )
        if self.acceptance_status == "owner_accepted" and any(entry.evidence_hash is None for entry in self.entries):
            raise ValueError("owner_accepted support matrix requires evidence hash for every entry")
        keys = [(entry.category, entry.feature) for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("support matrix entries must be unique")

    @property
    def matrix_hash(self) -> str:
        return sha256_hex(self._unsigned_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            **self._unsigned_dict(),
            "matrix_hash": self.matrix_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "EVMExecutionSupportMatrix":
        """Decode and verify a serialized matrix, including its self-hash."""
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list):
            raise ValueError("support matrix entries must be a list")
        entries: list[SupportEntry] = []
        for raw in raw_entries:
            if not isinstance(raw, Mapping):
                raise ValueError("support matrix entry must be an object")
            try:
                entries.append(SupportEntry(
                    category=raw["category"],
                    feature=raw["feature"],
                    status=SupportStatus(raw["status"]),
                    condition=raw.get("condition"),
                    evidence_hash=raw.get("evidence_hash"),
                    note=raw.get("note"),
                ))
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"invalid support matrix entry: {error}") from error
        try:
            matrix = cls(
                matrix_id=payload["matrix_id"],
                engine=payload["engine"],
                engine_revision=payload["engine_revision"],
                entries=tuple(entries),
                acceptance_status=payload.get("acceptance_status", "draft"),
                acceptance_owner=payload.get("acceptance_owner"),
                accepted_at=payload.get("accepted_at"),
                acceptance_agent=payload.get("acceptance_agent"),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid support matrix: {error}") from error
        if payload.get("matrix_hash") != matrix.matrix_hash:
            raise ValueError("support matrix hash mismatch")
        return matrix

    def status_for(self, category: str, feature: str) -> SupportStatus:
        for entry in self.entries:
            if entry.category == category and entry.feature == feature:
                return entry.status
        return SupportStatus.UNKNOWN

    def admits(self, required: tuple[tuple[str, str], ...]) -> bool:
        return all(
            self.status_for(category, feature)
            in {SupportStatus.SUPPORTED, SupportStatus.CONDITIONAL}
            for category, feature in required
        )

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "matrix_id": self.matrix_id,
            "engine": self.engine,
            "engine_revision": self.engine_revision,
            "entries": [entry.as_dict() for entry in sorted(self.entries, key=lambda item: (item.category, item.feature))],
            "acceptance_status": self.acceptance_status,
            "acceptance_owner": self.acceptance_owner,
            "accepted_at": self.accepted_at,
            "acceptance_agent": self.acceptance_agent,
        }


__all__ = ["EVMExecutionSupportMatrix", "SupportEntry", "SupportStatus"]


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and value == value.lower() and all(char in "0123456789abcdef" for char in value)
