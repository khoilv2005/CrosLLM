"""Offline fixed-template proposer used by the T0 ablation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from ..artifacts import ArtifactSymbol
from ..contracts.canonical import sha256_hex
from ..xlir import XLIRCompiler
from .proposal import ProposalSlot, ProposalSlotStatus, candidate_identity
from .runner import MethodRun, MethodTrack


class T0InputError(ValueError):
    """The public artifact pack is malformed or contains forbidden material."""


@dataclass(frozen=True, slots=True)
class T0Template:
    template_id: str
    kind: str
    operator: str
    left_state: str
    right_state: str
    selection: str

    def as_dict(self) -> dict[str, str]:
        return {
            "template_id": self.template_id,
            "kind": self.kind,
            "operator": self.operator,
            "left_state": self.left_state,
            "right_state": self.right_state,
            "selection": self.selection,
        }


@dataclass(frozen=True, slots=True)
class T0TemplateLibrary:
    generator_revision: str
    max_slots: int
    templates: tuple[T0Template, ...]

    @property
    def library_hash(self) -> str:
        return sha256_hex({
            "schema_version": 1,
            "generator_revision": self.generator_revision,
            "max_slots": self.max_slots,
            "templates": [template.as_dict() for template in self.templates],
        })

    @classmethod
    def from_file(cls, path: Path) -> "T0TemplateLibrary":
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as error:
            raise T0InputError(f"cannot read T0 template library {path}: {error}") from error
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise T0InputError("T0 template library schema_version must be 1")
        revision = raw.get("generator_revision")
        max_slots = raw.get("max_slots")
        rows = raw.get("templates")
        if not isinstance(revision, str) or not revision or not isinstance(max_slots, int) or max_slots <= 0 or not isinstance(rows, list) or not rows:
            raise T0InputError("T0 template library identity or templates are invalid")
        templates: list[T0Template] = []
        for row in rows:
            if not isinstance(row, dict):
                raise T0InputError("T0 template must be an object")
            template = T0Template(
                _string(row, "template_id"), _string(row, "kind"), _string(row, "operator"),
                _string(row, "left_state"), _string(row, "right_state"), _string(row, "selection"),
            )
            if template.kind != "invariant" or template.operator != "eq" or template.left_state not in {"pre", "post"} or template.right_state not in {"pre", "post"}:
                raise T0InputError(f"unsupported T0 template grammar: {template.template_id}")
            templates.append(template)
        ids = [template.template_id for template in templates]
        if len(ids) != len(set(ids)):
            raise T0InputError("T0 template IDs must be unique")
        return cls(revision, max_slots, tuple(templates))


@dataclass(frozen=True, slots=True)
class T0ProposalRun:
    """Deterministic T0 output plus provenance needed for an archive."""

    method_run: MethodRun
    template_library_hash: str
    selected_template_ids: tuple[str, ...]
    candidate_hashes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        payload = self.method_run.as_dict()
        payload.update({
            "template_library_hash": self.template_library_hash,
            "selected_template_ids": list(self.selected_template_ids),
            "candidate_hashes": list(self.candidate_hashes),
            "generator": "offline_deterministic_t0",
        })
        return payload


class T0DeterministicProposer:
    """Generate stable XLIR candidates from public scalar storage symbols."""

    def __init__(self, library: T0TemplateLibrary) -> None:
        self.library = library
        if not library.templates:
            raise T0InputError("T0 requires at least one template")

    def propose(
        self,
        artifact_pack: Mapping[str, Any],
        *,
        attempt_id: str,
        artifact_pack_hash: str | None = None,
        proposal_slots: int = 8,
    ) -> T0ProposalRun:
        if not attempt_id:
            raise T0InputError("T0 attempt_id is required")
        if proposal_slots <= 0 or proposal_slots > self.library.max_slots:
            raise T0InputError("proposal_slots must be within the T0 library maximum")
        _assert_public_pack(artifact_pack)
        symbols = _public_scalar_symbols(artifact_pack)
        pack_hash = artifact_pack_hash or sha256_hex(artifact_pack)
        slots: list[ProposalSlot] = []
        selected: list[str] = []
        candidate_hashes: list[str] = []
        candidates = self._candidate_payloads(symbols)
        for index in range(proposal_slots):
            slot_id = f"{attempt_id}:slot:{index}"
            if index < len(candidates):
                template_id, payload = candidates[index]
                digest, canonical_hash = candidate_identity(payload)
                compiler = XLIRCompiler.from_symbols(list(symbols))
                compiled = compiler.compile(payload)
                if not compiled.ok or compiled.invariant is None:
                    raise T0InputError(f"generated T0 candidate did not compile: {template_id}")
                canonical_hash = compiled.invariant.canonical_hash
                slots.append(ProposalSlot(slot_id, index, ProposalSlotStatus.CANDIDATE, candidate=payload, canonical_ast_hash=canonical_hash))
                selected.append(template_id)
                candidate_hashes.append(digest)
            else:
                slots.append(ProposalSlot(slot_id, index, ProposalSlotStatus.ABSTAIN, reason="no_remaining_public_scalar_symbol"))
        method_run = MethodRun(
            MethodTrack.T0,
            "deterministic",
            attempt_id,
            self.library.library_hash,
            pack_hash,
            {
                "generator_revision": self.library.generator_revision,
                "template_library_hash": self.library.library_hash,
                "proposal_slots": proposal_slots,
                "provider": "none",
                "thinking": "not_applicable",
            },
            tuple(slots),
        )
        return T0ProposalRun(method_run, self.library.library_hash, tuple(selected), tuple(candidate_hashes))

    def _candidate_payloads(self, symbols: tuple[ArtifactSymbol, ...]) -> list[tuple[str, dict[str, object]]]:
        result: list[tuple[str, dict[str, object]]] = []
        for symbol in symbols:
            template = self.library.templates[0]
            payload = {
                "kind": template.kind,
                "invariant_id": f"t0.{template.template_id}.{symbol.symbol_id}",
                "body": {
                    "kind": "binary",
                    "operator": template.operator,
                    "left": {"kind": "symbol", "symbol_id": symbol.symbol_id, "state": template.left_state},
                    "right": {"kind": "symbol", "symbol_id": symbol.symbol_id, "state": template.right_state},
                },
            }
            result.append((template.template_id, payload))
        return result


def _public_scalar_symbols(artifact_pack: Mapping[str, Any]) -> tuple[ArtifactSymbol, ...]:
    public_files = artifact_pack.get("public_files")
    storage = public_files.get("storage_symbols.json") if isinstance(public_files, Mapping) else None
    rows = storage.get("symbols") if isinstance(storage, Mapping) else None
    if not isinstance(rows, list):
        raise T0InputError("public artifact pack has no storage_symbols.json symbols")
    symbols: list[ArtifactSymbol] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise T0InputError("public storage symbol must be an object")
        fields = tuple(row.get(field) for field in ("symbol_id", "path", "name", "domain", "kind", "type"))
        if any(not isinstance(value, str) or not value for value in fields):
            raise T0InputError("public storage symbol has incomplete identity")
        if row["kind"] != "storage" or row["type"] not in {"bool", "uint256", "int256", "address", "bytes32"}:
            continue
        symbols.append(ArtifactSymbol(*fields))
    return tuple(sorted(symbols, key=lambda item: item.symbol_id))


def _assert_public_pack(value: object, path: str = "$") -> None:
    forbidden = {"gold_property", "trigger_calldata", "exploit_payload", "mutation_diff", "private_key", "rpc_url", "property_oracle"}
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise T0InputError(f"{path}: public artifact keys must be strings")
            if key.lower() in forbidden:
                raise T0InputError(f"{path}.{key}: forbidden private field")
            _assert_public_pack(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _assert_public_pack(nested, f"{path}[{index}]")


def _string(value: Mapping[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise T0InputError(f"T0 template {field} must be a non-empty string")
    return item


__all__ = ["T0DeterministicProposer", "T0InputError", "T0ProposalRun", "T0Template", "T0TemplateLibrary"]
