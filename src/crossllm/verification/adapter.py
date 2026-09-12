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
from .runtime import BindingStatus, CaseRuntimeBindings, SymbolRuntimeBinding


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
        }


class RuntimeCandidateAdapter:
    """Compile and bind one proposal without executing it."""

    def __init__(self, case: CaseRuntimeBindings, symbols: list[ArtifactSymbol], *, maximum_ast_nodes: int = 256) -> None:
        self.case = case
        self.symbols = tuple(symbols)
        self.compiler = XLIRCompiler.from_symbols(list(self.symbols), maximum_ast_nodes)
        self._bindings = {item.symbol_id: item for item in case.symbols}

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
            "runtime_hash": self.case.runtime.runtime_hash,
            "canonical_ast_hash": invariant.canonical_hash,
            "predicate": invariant.body.as_dict(),
            "actions": [action.as_dict() for action in bound_actions],
            "bounds": {},
            "initial_state": dict(self.case.runtime.initial_state),
        }
        status = AdapterStatus.READY if not self.case.missing_fields and all(action.executable for action in bound_actions) else AdapterStatus.GROUNDED
        return RuntimeCandidatePlan(candidate, status, invariant.canonical_hash, invariant, tuple(resolved), (), request)


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
