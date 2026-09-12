"""Persistent duplicate-safe cache for candidate verification outcomes."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping

from ..contracts.canonical import sha256_hex


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class VerificationCacheKey:
    """All inputs that can change a verification result."""

    case_runtime_hash: str
    canonical_ast_hash: str
    adapter_revision: str
    bounds_hash: str
    replay_spec_hash: str | None = None

    def __post_init__(self) -> None:
        for name in ("case_runtime_hash", "canonical_ast_hash", "bounds_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        if not isinstance(self.adapter_revision, str) or not self.adapter_revision:
            raise ValueError("adapter_revision is required")
        if self.replay_spec_hash is not None and _HEX64.fullmatch(self.replay_spec_hash) is None:
            raise ValueError("replay_spec_hash must be a lowercase SHA-256 digest")

    @property
    def key_hash(self) -> str:
        return sha256_hex(self.as_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            "case_runtime_hash": self.case_runtime_hash,
            "canonical_ast_hash": self.canonical_ast_hash,
            "adapter_revision": self.adapter_revision,
            "bounds_hash": self.bounds_hash,
            "replay_spec_hash": self.replay_spec_hash,
        }


@dataclass(frozen=True, slots=True)
class CacheLookup:
    record: Mapping[str, Any] | None
    hit: bool


class FileVerificationCache:
    """Atomic JSON cache; a key can never be overwritten with another result."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = RLock()
        self._entries: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            self._load()

    def lookup(self, key: VerificationCacheKey) -> CacheLookup:
        with self._lock:
            record = self._entries.get(key.key_hash)
            return CacheLookup(dict(record) if record is not None else None, record is not None)

    def put(self, key: VerificationCacheKey, outcome: Mapping[str, Any]) -> None:
        if not isinstance(outcome, Mapping):
            raise ValueError("cached outcome must be an object")
        record = {
            "schema_version": 1,
            "record_type": "verification_cache_entry",
            "cache_key": key.as_dict(),
            "cache_key_hash": key.key_hash,
            "outcome": dict(outcome),
        }
        with self._lock:
            current = self._entries.get(key.key_hash)
            if current is not None:
                if current != record:
                    raise ValueError("verification cache key already has a different outcome")
                return
            candidate = dict(self._entries)
            candidate[key.key_hash] = record
            self._persist(candidate)
            self._entries = candidate

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"cannot load verification cache: {error}") from error
        if not isinstance(payload, dict) or payload.get("schema_version") != 1 or payload.get("record_type") != "verification_cache":
            raise ValueError("invalid verification cache header")
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            raise ValueError("verification cache entries must be an object")
        for key_hash, record in entries.items():
            if not isinstance(key_hash, str) or _HEX64.fullmatch(key_hash) is None or not isinstance(record, dict):
                raise ValueError("verification cache contains an invalid entry")
            if record.get("cache_key_hash") != key_hash:
                raise ValueError("verification cache key hash mismatch")
            self._entries[key_hash] = record

    def _persist(self, entries: Mapping[str, Mapping[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "record_type": "verification_cache",
            "entries": {key: dict(entries[key]) for key in sorted(entries)},
        }
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
        temporary.replace(self.path)


__all__ = ["CacheLookup", "FileVerificationCache", "VerificationCacheKey"]
