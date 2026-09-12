"""Candidate-to-runtime adapter for the shared verification pipeline.

The adapter is deliberately separate from search and replay.  Its job is to
compile untrusted XLIR, resolve every referenced symbol against the case's
runtime binding table, and emit a typed search request.  It never turns a
model's text into Solidity and never treats a grounded predicate as a finding.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from ..artifacts import ArtifactSymbol, extract_storage_symbols
from ..contracts.canonical import sha256_hex
from ..xlir import XLIRCompiler
from ..xlir.model import (
    Binary,
    BoundRef,
    Expression,
    Invariant,
    Quantifier,
    SymbolRef,
    Temporal,
    Unary,
)
from .records import CandidateInput
from .cache import VerificationCacheKey
from .runtime import BindingStatus, CaseRuntimeBindings, SymbolRuntimeBinding


_DEFERRED_RUNTIME_FIELDS = frozenset({"actor_addresses", "contract_addresses"})


class AdapterStatus(StrEnum):
    ABSTAINED = "abstained"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"
    GROUNDED = "grounded"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class RuntimeCandidatePlan:
    """Typed, auditable hand-off from XLIR grounding to a search backend."""

    candidate: CandidateInput
    status: AdapterStatus
    canonical_ast_hash: str | None
    invariant: Invariant | None
    symbol_bindings: tuple[SymbolRuntimeBinding, ...]
    diagnostics: tuple[str, ...]
    search_request: Mapping[str, Any] | None = None
    cache_key: str | None = None

    @property
    def executable(self) -> bool:
        return self.status is AdapterStatus.READY

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "record_type": "runtime_candidate_plan",
            "campaign_id": self.candidate.campaign_id,
            "attempt_id": self.candidate.attempt_id,
            "arm": self.candidate.arm,
            "slot_index": self.candidate.slot_index,
            "slot_id": self.candidate.slot_id,
            "status": self.status.value,
            "canonical_ast_hash": self.canonical_ast_hash,
            "symbol_bindings": [item.as_dict() for item in self.symbol_bindings],
            "diagnostics": list(self.diagnostics),
            "search_request": dict(self.search_request) if self.search_request is not None else None,
            "cache_key": self.cache_key,
        }


class RuntimeCandidateAdapter:
    """Compile and bind one proposal without executing it."""

    def __init__(
        self,
        case: CaseRuntimeBindings,
        symbols: list[ArtifactSymbol],
        *,
        maximum_ast_nodes: int = 256,
        adapter_revision: str = "runtime-adapter-v1",
        bounds: Mapping[str, Any] | None = None,
        replay_spec_hash: str | None = None,
        executor_spec_hash: str | None = None,
        deferred_runtime_fields: frozenset[str] = frozenset(),
    ) -> None:
        self.case = case
        self.symbols = tuple(symbols)
        self.compiler = XLIRCompiler.from_symbols(list(self.symbols), maximum_ast_nodes)
        self._bindings = {item.symbol_id: item for item in case.symbols}
        if not adapter_revision:
            raise ValueError("adapter_revision is required")
        if bounds is not None and not isinstance(bounds, Mapping):
            raise ValueError("adapter bounds must be a mapping")
        self.adapter_revision = adapter_revision
        self.bounds = dict(bounds or {})
        self.replay_spec_hash = replay_spec_hash
        self.executor_spec_hash = executor_spec_hash
        self.deferred_runtime_fields = frozenset(deferred_runtime_fields)
        unknown_deferred = self.deferred_runtime_fields - _DEFERRED_RUNTIME_FIELDS
        if unknown_deferred:
            raise ValueError(f"unsupported deferred runtime fields: {sorted(unknown_deferred)}")

    def adapt(self, candidate: CandidateInput) -> RuntimeCandidatePlan:
        if candidate.proposal_status != "candidate" or candidate.candidate is None:
            return RuntimeCandidatePlan(candidate, AdapterStatus.ABSTAINED, None, None, (), ("proposal_slot_not_candidate",))
        payload = candidate.candidate
        if isinstance(payload, Invariant):
            invariant = payload
            diagnostics: tuple[str, ...] = ()
        else:
            result = self.compiler.compile(payload)
            if result.abstained:
                return RuntimeCandidatePlan(candidate, AdapterStatus.ABSTAINED, None, None, (), ("proposal_explicitly_abstained",))
            if not result.ok or result.invariant is None:
                diagnostics = tuple(f"{item.code}:{item.path}:{item.message}" for item in result.diagnostics)
                return RuntimeCandidatePlan(candidate, AdapterStatus.INVALID, None, None, (), diagnostics)
            invariant = result.invariant
            diagnostics = ()
        referenced = _symbol_references(invariant.body)
        resolved: list[SymbolRuntimeBinding] = []
        failures: list[str] = list(diagnostics)
        for reference in referenced:
            binding = self._bindings.get(reference.symbol_id)
            if binding is None:
                failures.append(f"missing_runtime_binding:{reference.symbol_id}")
                continue
            resolved.append(binding)
            if binding.status is not BindingStatus.BOUND:
                failures.append(f"runtime_binding_{binding.status.value}:{reference.symbol_id}:{binding.reason or 'unspecified'}")
                continue
            if binding.symbol_type != reference.value_type.value:
                failures.append(f"runtime_type_mismatch:{reference.symbol_id}:{binding.symbol_type}:{reference.value_type.value}")
            if reference.domain != binding.domain:
                failures.append(f"runtime_domain_mismatch:{reference.symbol_id}:{binding.domain}:{reference.domain}")
            if reference.state not in binding.state_locations:
                failures.append(f"runtime_state_unavailable:{reference.symbol_id}:{reference.state}")
        if failures:
            return RuntimeCandidatePlan(
                candidate, AdapterStatus.UNSUPPORTED, invariant.canonical_hash, invariant,
                tuple(resolved), tuple(failures), None,
            )
        bound_actions = tuple(action for action in self.case.actions if action.status is BindingStatus.BOUND)
        if not bound_actions:
            return RuntimeCandidatePlan(
                candidate, AdapterStatus.UNSUPPORTED, invariant.canonical_hash, invariant,
                tuple(resolved), ("no_bound_runtime_actions",), None,
            )
        request = {
            "schema_version": 1,
            "record_type": "candidate_runtime_search_request",
            "lineage_id": self.case.runtime.lineage_id,
            "case_id": self.case.runtime.case_id,
            "instance_id": self.case.runtime.instance_id,
            "runtime_hash": self.case.runtime.runtime_hash,
            "canonical_ast_hash": invariant.canonical_hash,
            "predicate": invariant.body.as_dict(),
            "actions": [action.as_dict() for action in bound_actions],
            "adapter_revision": self.adapter_revision,
            "bounds": dict(self.bounds),
            "deferred_runtime_fields": sorted(self.deferred_runtime_fields),
            "replay_spec_hash": self.replay_spec_hash,
            "executor_spec_hash": self.executor_spec_hash,
            "artifact_hash": self.case.runtime.source_artifact_hash,
            "deployment_hash": self.case.runtime.deployment_hash,
            "initial_state_hash": sha256_hex(self.case.runtime.initial_state),
            "source_domain": self.case.runtime.source_domain,
            "destination_domain": self.case.runtime.destination_domain,
            "actors": dict(self.case.runtime.actors),
            "initial_state": dict(self.case.runtime.initial_state),
        }
        missing_fields = set(self.case.missing_fields)
        runtime_ready = not missing_fields or missing_fields.issubset(self.deferred_runtime_fields)
        status = AdapterStatus.READY if runtime_ready and all(action.executable for action in bound_actions) else AdapterStatus.GROUNDED
        cache_key = VerificationCacheKey(
            case_runtime_hash=self.case.runtime.runtime_hash,
            canonical_ast_hash=invariant.canonical_hash,
            adapter_revision=self.adapter_revision,
            bounds_hash=sha256_hex(self.bounds),
            replay_spec_hash=self.replay_spec_hash,
            executor_spec_hash=self.executor_spec_hash,
        ).key_hash
        return RuntimeCandidatePlan(candidate, status, invariant.canonical_hash, invariant, tuple(resolved), (), request, cache_key)


def public_xlir_symbols(repo_root: Path, lineage_id: str) -> list[ArtifactSymbol]:
    """Load the same public scalar symbol table exposed to the proposer."""

    root = Path(repo_root).resolve() / "dataset" / "artifacts" / lineage_id
    symbols = _read_symbols(root / "symbols.json")
    assignments = symbols.get("domain_assignments")
    if not isinstance(assignments, Mapping):
        raise ValueError(f"{lineage_id}: domain_assignments missing")
    extracted = extract_storage_symbols(root, assignments)
    return list(extracted.symbols)


def _read_symbols(path: Path) -> dict[str, Any]:
    import json

    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: symbols must be an object")
    return value


def _symbol_references(expression: Expression) -> tuple[SymbolRef, ...]:
    found: dict[tuple[str, str, str], SymbolRef] = {}

    def visit(node: Expression) -> None:
        if isinstance(node, SymbolRef):
            found[(node.symbol_id, node.state, node.domain)] = node
            return
        if isinstance(node, (Unary, Temporal)):
            visit(node.operand)
            return
        if isinstance(node, Binary):
            visit(node.left)
            visit(node.right)
            return
        if isinstance(node, Quantifier):
            visit(node.body)
            return
        if isinstance(node, BoundRef):
            return

    visit(expression)
    return tuple(found[key] for key in sorted(found))


__all__ = [
    "AdapterStatus", "RuntimeCandidatePlan", "RuntimeCandidateAdapter", "public_xlir_symbols",
]
