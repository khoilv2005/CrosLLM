"""Deterministic sanitization mappings and trace correspondence checks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ..contracts.canonical import sha256_hex


_KINDS = {"identifier", "selector", "signature", "domain"}
_SCOPES = {"source", "destination", "shared"}


@dataclass(frozen=True, slots=True)
class SanitizationMapping:
    """One exact replacement in the private-to-public correspondence map."""

    kind: str
    original: str
    sanitized: str
    scope: str = "shared"

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"unsupported sanitization mapping kind: {self.kind}")
        if self.scope not in _SCOPES:
            raise ValueError(f"unsupported sanitization mapping scope: {self.scope}")
        if not self.original or not self.sanitized:
            raise ValueError("sanitization mapping values must be non-empty")
        if self.original == self.sanitized:
            raise ValueError("sanitization mapping must change its value")

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "original": self.original,
            "sanitized": self.sanitized,
            "scope": self.scope,
        }


@dataclass(frozen=True, slots=True)
class TraceCorrespondence:
    """Hashes proving which private trace was transformed into a public trace."""

    original_trace_hash: str
    sanitized_trace_hash: str
    mapping_hash: str
    event_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "original_trace_hash": self.original_trace_hash,
            "sanitized_trace_hash": self.sanitized_trace_hash,
            "mapping_hash": self.mapping_hash,
            "event_count": self.event_count,
        }


@dataclass(frozen=True, slots=True)
class SanitizedTrace:
    """Public trace rows together with their private correspondence record."""

    events: tuple[dict[str, object], ...]
    correspondence: TraceCorrespondence

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "events": [dict(event) for event in self.events],
            "correspondence": self.correspondence.as_dict(),
        }


class SanitizationMap:
    """Apply exact, collision-free replacements to symbols and trace rows.

    Mapping is intentionally exact rather than substring-based. A selector and
    its signature therefore need separate entries when both are changed. Domain
    replacements are applied first to each trace row so scoped replacements use
    the public domain consistently.
    """

    def __init__(self, mappings: Iterable[SanitizationMapping]) -> None:
        normalized = tuple(sorted(mappings, key=lambda item: (item.kind, item.scope, item.original)))
        by_key: dict[tuple[str, str, str], SanitizationMapping] = {}
        by_target: dict[tuple[str, str, str], SanitizationMapping] = {}
        for mapping in normalized:
            key = (mapping.kind, mapping.scope, mapping.original)
            target = (mapping.kind, mapping.scope, mapping.sanitized)
            if key in by_key:
                raise ValueError(f"duplicate sanitization mapping: {key}")
            previous = by_target.get(target)
            if previous is not None and previous.original != mapping.original:
                raise ValueError(f"sanitization collision: {target}")
            by_key[key] = mapping
            by_target[target] = mapping
        self.mappings = normalized
        self.mapping_hash = sha256_hex([mapping.as_dict() for mapping in normalized])
        self._by_key = by_key

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mapping_hash": self.mapping_hash,
            "mappings": [mapping.as_dict() for mapping in self.mappings],
        }

    def translate(self, kind: str, value: str, *, scope: str = "shared") -> str:
        """Translate one exact value, falling back to a shared mapping."""
        if kind not in _KINDS:
            raise ValueError(f"unsupported sanitization mapping kind: {kind}")
        if scope not in _SCOPES:
            raise ValueError(f"unsupported sanitization mapping scope: {scope}")
        mapping = self._by_key.get((kind, scope, value))
        if mapping is None and scope != "shared":
            mapping = self._by_key.get((kind, "shared", value))
        return mapping.sanitized if mapping is not None else value

    def rewrite_symbol(self, symbol: Any) -> Any:
        """Return an ArtifactSymbol-like object with ID/name/domain in sync."""
        scope = symbol.domain if symbol.domain in _SCOPES else "shared"
        public_domain = self.translate("domain", symbol.domain, scope="shared")
        public_id = self.translate("identifier", symbol.symbol_id, scope=scope)
        public_name = self.translate("identifier", symbol.name, scope=scope)
        if hasattr(symbol, "__dataclass_fields__"):
            from dataclasses import replace
            return replace(symbol, symbol_id=public_id, name=public_name, domain=public_domain)
        raise TypeError("rewrite_symbol expects an ArtifactSymbol-like dataclass")

    def rewrite_trace(self, events: Iterable[Mapping[str, object]]) -> SanitizedTrace:
        """Rewrite trace metadata and return hash-linked correspondence.

        Recognized fields are deliberately narrow. Unknown fields are copied
        unchanged so opaque proof objects remain byte-for-byte represented in
        the canonical trace. A row with a mapped selector/signature/domain is
        transformed as one unit; stale private values cannot remain in those
        recognized fields.
        """
        original = tuple(self._copy_event(event) for event in events)
        rewritten: list[dict[str, object]] = []
        for event in original:
            public = dict(event)
            original_domain = event.get("domain")
            if isinstance(original_domain, str):
                public["domain"] = self.translate("domain", original_domain)
            scope_value = public.get("domain", original_domain)
            scope = scope_value if scope_value in _SCOPES else "shared"
            for field_name, kind in (
                ("selector", "selector"),
                ("signature", "signature"),
                ("symbol_id", "identifier"),
                ("emitter", "identifier"),
                ("recipient", "identifier"),
            ):
                value = event.get(field_name)
                if isinstance(value, str):
                    public[field_name] = self.translate(kind, value, scope=scope)
            for field_name in ("source_domain", "destination_domain"):
                value = event.get(field_name)
                if isinstance(value, str):
                    public[field_name] = self.translate("domain", value)
            rewritten.append(public)
        public_events = tuple(rewritten)
        correspondence = TraceCorrespondence(
            original_trace_hash=sha256_hex(list(original)),
            sanitized_trace_hash=sha256_hex(list(public_events)),
            mapping_hash=self.mapping_hash,
            event_count=len(original),
        )
        return SanitizedTrace(public_events, correspondence)

    @staticmethod
    def _copy_event(event: Mapping[str, object]) -> dict[str, object]:
        if not isinstance(event, Mapping):
            raise ValueError("sanitization trace events must be objects")
        return dict(event)
