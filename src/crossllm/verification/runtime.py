"""Gold-free runtime binding records for source-backed case artifacts.

This module is intentionally a metadata boundary.  It turns the public
artifact and harness descriptions into explicit bindings, but it never reads
mutation patches, trigger validation, property assessment, or replay traces.
Bindings that cannot be established from those public inputs remain
``unsupported``/``missing`` instead of being guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .records import CaseRuntimeSpec


class BindingStatus(StrEnum):
    """Resolution status for a symbol or action binding."""

    BOUND = "bound"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class SymbolRuntimeBinding:
    """One public XLIR storage symbol mapped to a runtime location."""

    symbol_id: str
    symbol_type: str | None
    domain: str
    contract: str
    location: str | None
    state_locations: tuple[str, ...]
    slot: int | None = None
    offset_bytes: int | None = None
    getter: str | None = None
    decode_rule: str | None = None
    status: BindingStatus = BindingStatus.UNSUPPORTED
    reason: str | None = None
    evidence: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.symbol_id or not self.domain or not self.contract:
            raise ValueError("symbol binding identity is incomplete")
        if any(state not in {"pre", "post"} for state in self.state_locations):
            raise ValueError("symbol binding state must be pre or post")
        if len(set(self.state_locations)) != len(self.state_locations):
            raise ValueError("symbol binding states must be unique")
        if self.slot is not None and self.slot < 0:
            raise ValueError("symbol binding slot must be non-negative")
        if self.offset_bytes is not None and not 0 <= self.offset_bytes < 32:
            raise ValueError("symbol binding offset must be a byte within a storage word")

    @property
    def executable(self) -> bool:
        return self.status is BindingStatus.BOUND and bool(self.location)

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol_id": self.symbol_id,
            "symbol_type": self.symbol_type,
            "domain": self.domain,
            "contract": self.contract,
            "location": self.location,
            "state_locations": list(self.state_locations),
            "slot": self.slot,
            "offset_bytes": self.offset_bytes,
            "getter": self.getter,
            "decode_rule": self.decode_rule,
            "status": self.status.value,
            "reason": self.reason,
            "evidence": dict(self.evidence) if self.evidence is not None else None,
            "executable": self.executable,
        }


@dataclass(frozen=True, slots=True)
class ActionRuntimeBinding:
    """One harness workflow action mapped to a public ABI function."""

    action_id: str
    action: str
    caller_role: str
    domain: str
    contract: str | None
    function_symbol_id: str | None
    signature: str | None
    selector: str | None
    calldata_encoder: Mapping[str, Any] | None
    value_policy: str
    state_transition: str
    status: BindingStatus
    reason: str | None = None
    evidence: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.action_id or not self.action or not self.caller_role or not self.domain:
            raise ValueError("action binding identity is incomplete")
        if self.selector is not None and re.fullmatch(r"0x[0-9a-fA-F]{8}", self.selector) is None:
            raise ValueError("action selector must be a four-byte hex value")

    @property
    def executable(self) -> bool:
        return self.status is BindingStatus.BOUND and self.signature is not None and self.selector is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "action": self.action,
            "caller_role": self.caller_role,
            "domain": self.domain,
            "contract": self.contract,
            "function_symbol_id": self.function_symbol_id,
            "signature": self.signature,
            "selector": self.selector,
            "calldata_encoder": dict(self.calldata_encoder) if self.calldata_encoder is not None else None,
            "value_policy": self.value_policy,
            "state_transition": self.state_transition,
            "status": self.status.value,
            "reason": self.reason,
            "evidence": dict(self.evidence) if self.evidence is not None else None,
            "executable": self.executable,
        }


@dataclass(frozen=True, slots=True)
class CaseRuntimeBindings:
    """All public runtime bindings for one mutant or control case."""

    runtime: CaseRuntimeSpec
    symbols: tuple[SymbolRuntimeBinding, ...]
    actions: tuple[ActionRuntimeBinding, ...]
    missing_fields: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()

    @property
    def bound_symbol_count(self) -> int:
        return sum(item.status is BindingStatus.BOUND for item in self.symbols)

    @property
    def bound_action_count(self) -> int:
        return sum(item.status is BindingStatus.BOUND for item in self.actions)

    @property
    def executable_action_count(self) -> int:
        return sum(item.executable for item in self.actions)

    @property
    def status(self) -> str:
        if self.diagnostics:
            return "invalid"
        if not self.symbols and not self.actions:
            return "unsupported"
        if self.bound_symbol_count or self.bound_action_count:
            return "metadata_bound" if not self.missing_fields else "partial"
        return "unsupported"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "record_type": "case_runtime_bindings",
            "case_id": self.runtime.case_id,
            "lineage_id": self.runtime.lineage_id,
            "instance_id": self.runtime.instance_id,
            "runtime": self.runtime.as_dict(),
            "status": self.status,
            "missing_fields": list(self.missing_fields),
            "diagnostics": list(self.diagnostics),
            "symbols": [item.as_dict() for item in self.symbols],
            "actions": [item.as_dict() for item in self.actions],
            "coverage": {
                "symbol_total": len(self.symbols),
                "symbol_bound": self.bound_symbol_count,
                "action_total": len(self.actions),
                "action_bound": self.bound_action_count,
                "action_executable": self.executable_action_count,
            },
        }


@dataclass(frozen=True, slots=True)
class RuntimeBindingMatrix:
    """Deterministic report over every discovered case."""

    cases: tuple[CaseRuntimeBindings, ...]
    repository_root: str

    @property
    def counts(self) -> dict[str, int]:
        counts = {status: 0 for status in ("metadata_bound", "partial", "unsupported", "invalid")}
        for case in self.cases:
            counts[case.status] = counts.get(case.status, 0) + 1
        return counts

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "record_type": "runtime_binding_matrix",
            "scope": "public_case_artifacts_only",
            "gold_fields_read": False,
            "repository_root": self.repository_root,
            "case_count": len(self.cases),
            "counts": self.counts,
            "cases": [case.as_dict() for case in self.cases],
        }


_STORAGE_TYPES = {
    "t_bool": "bool",
    "t_uint256": "uint256",
    "t_int256": "int256",
    "t_address": "address",
    "t_bytes32": "bytes32",
}
_WIDTHS = {"bool": 1, "uint256": 32, "int256": 32, "address": 20, "bytes32": 32}
_SLOT_RE = re.compile(r"^storage\((\d+)\)$")
_HEX_ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")


def load_case_runtime(repo_root: Path, lineage_id: str, case_id: str) -> CaseRuntimeBindings:
    """Build bindings for one case using only non-gold runtime metadata."""

    root = Path(repo_root).resolve()
    lineage_root = root / "dataset" / "artifacts" / lineage_id
    case_root = lineage_root / "cases" / case_id
    harness_path = root / "dataset" / "harness" / lineage_id / "harness_config.json"
    required = {
        "metadata": case_root / "metadata.json",
        "build_manifest": case_root / "build_manifest.json",
        "deployment": case_root / "deployment.json",
        "paired_harness": case_root / "paired_harness.json",
        "symbols": lineage_root / "symbols.json",
        "scope": lineage_root / "scope.json",
        "channel_profile": lineage_root / "channel_profile.json",
        "harness_config": harness_path,
    }
    missing = tuple(sorted(name for name, path in required.items() if not path.is_file()))
    if missing:
        return _unsupported_case(root, lineage_id, case_id, missing)
    try:
        metadata = _read_object(required["metadata"])
        build_manifest = _read_object(required["build_manifest"])
        deployment = _read_object(required["deployment"])
        paired_harness = _read_object(required["paired_harness"])
        symbols = _read_object(required["symbols"])
        scope = _read_object(required["scope"])
        profile = _read_object(required["channel_profile"])
        harness = _read_object(required["harness_config"])
        runtime = _build_runtime_spec(
            root, lineage_id, case_id, metadata, build_manifest, deployment,
            paired_harness, profile, scope, harness,
        )
        symbol_bindings = _build_symbol_bindings(lineage_root, case_root, symbols, harness)
        action_bindings = _build_action_bindings(lineage_root, case_root, symbols, harness)
        missing_fields = _runtime_missing_fields(runtime, action_bindings, deployment, harness)
        diagnostics = tuple(_validate_runtime_artifacts(case_root, build_manifest, paired_harness))
        return CaseRuntimeBindings(runtime, symbol_bindings, action_bindings, missing_fields, diagnostics)
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
        return _unsupported_case(root, lineage_id, case_id, (), (str(error),))


def build_runtime_binding_matrix(repo_root: Path, lineages: tuple[str, ...] | None = None) -> RuntimeBindingMatrix:
    """Scan cases in stable order and produce a resumable, non-gold matrix."""

    root = Path(repo_root).resolve()
    artifacts = root / "dataset" / "artifacts"
    selected = set(lineages) if lineages is not None else None
    rows: list[CaseRuntimeBindings] = []
    for lineage_root in sorted(path for path in artifacts.iterdir() if path.is_dir()):
        if selected is not None and lineage_root.name not in selected:
            continue
        cases_root = lineage_root / "cases"
        if not cases_root.is_dir():
            continue
        for case_root in sorted(path for path in cases_root.iterdir() if path.is_dir()):
            rows.append(load_case_runtime(root, lineage_root.name, case_root.name))
    # The report is copied to the VM and compared across machines.  An
    # absolute checkout path would make equivalent matrices differ for no
    # semantic reason.
    return RuntimeBindingMatrix(tuple(rows), ".")


def _build_runtime_spec(
    root: Path,
    lineage_id: str,
    case_id: str,
    metadata: Mapping[str, Any],
    build_manifest: Mapping[str, Any],
    deployment: Mapping[str, Any],
    paired_harness: Mapping[str, Any],
    profile: Mapping[str, Any],
    scope: Mapping[str, Any],
    harness: Mapping[str, Any],
) -> CaseRuntimeSpec:
    _require_identity(metadata, lineage_id, case_id)
    domain_pair = harness.get("domain_pair")
    source = domain_pair.get("source") if isinstance(domain_pair, Mapping) else None
    destination = domain_pair.get("destination") if isinstance(domain_pair, Mapping) else None
    source_domain = _nonempty(source, "name")
    destination_domain = _nonempty(destination, "name")
    workflow = harness.get("workflow_coverage")
    workflow = workflow if isinstance(workflow, Mapping) else {}
    allowed = workflow.get("allowed_actions")
    supported_actions = _flatten_actions(allowed)
    normal = workflow.get("normal_workflow")
    normal = normal if isinstance(normal, Mapping) else {}
    observation_points = _unique_strings(normal.get("assertions", ()))
    if not observation_points:
        observation_points = _unique_strings(scope.get("entry_points", ()))
    contract_addresses = _extract_addresses(deployment)
    actors = _extract_addresses(harness.get("actors"))
    initialization = workflow.get("state_initialization")
    initial_state = dict(initialization) if isinstance(initialization, Mapping) else {}
    compiler = harness.get("compiler")
    compiler_hash = compiler.get("binary_sha256") if isinstance(compiler, Mapping) else None
    if not isinstance(compiler_hash, str):
        compiler_hash = _sha256_file(root / "dataset" / "artifacts" / lineage_id / "source_receipt.json")
    profile_hash = _sha256_file(root / "dataset" / "artifacts" / lineage_id / "channel_profile.json")
    source_hash = _hash_field(metadata, "built_source_sha256", build_manifest.get("source", {}), "sha256")
    build_hash = _hash_field(metadata, "artifact_manifest_sha256", None, None)
    deployment_hash = _hash_field(metadata, "deployment_config_sha256", None, None)
    metadata_public = {
        "protocol": harness.get("protocol"),
        "source_backed": harness.get("source_backed"),
        "harness_status": harness.get("harness_status"),
        "harness_version": harness.get("harness_version"),
        "test_runner": harness.get("test_runner"),
        "test_contract": harness.get("test_contract"),
        "workflow_file": harness.get("workflow_file"),
        "deployment_scope": deployment.get("scope"),
        "paired_runner": paired_harness.get("runner"),
        "profile": dict(profile),
    }
    return CaseRuntimeSpec(
        case_id=case_id,
        lineage_id=lineage_id,
        instance_id=case_id,
        source_artifact_hash=source_hash,
        build_manifest_hash=build_hash,
        deployment_hash=deployment_hash,
        profile_hash=profile_hash,
        compiler_hash=compiler_hash,
        source_domain=source_domain,
        destination_domain=destination_domain,
        supported_actions=supported_actions,
        observation_points=observation_points,
        contract_addresses=contract_addresses,
        actors=actors,
        initial_state=initial_state,
        runtime_mode="source_backed_local_evm" if harness.get("source_backed") is True else "unknown",
        metadata=metadata_public,
    )


def _build_symbol_bindings(
    lineage_root: Path,
    case_root: Path,
    symbols: Mapping[str, Any],
    harness: Mapping[str, Any],
) -> tuple[SymbolRuntimeBinding, ...]:
    rows = symbols.get("stable_symbols")
    if not isinstance(rows, list):
        raise ValueError("symbols.json has no stable_symbols list")
    result: list[SymbolRuntimeBinding] = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("kind") != "storage":
            continue
        symbol_id = _nonempty(row, "symbol_id")
        contract = _nonempty(row, "contract")
        domain = _nonempty(row, "domain")
        raw_type = _nonempty(row, "type")
        xlir_type = _STORAGE_TYPES.get(raw_type)
        if xlir_type is None:
            result.append(SymbolRuntimeBinding(
                symbol_id, None, domain, contract, None, ("pre", "post"),
                status=BindingStatus.UNSUPPORTED,
                reason="storage_type_not_supported_by_xlir",
                evidence={"storage_type": raw_type},
            ))
            continue
        slot_match = _SLOT_RE.fullmatch(str(row.get("signature", "")))
        if slot_match is None:
            result.append(SymbolRuntimeBinding(
                symbol_id, xlir_type, domain, contract, None, ("pre", "post"),
                status=BindingStatus.MISSING, reason="storage_slot_not_declared",
            ))
            continue
        slot = int(slot_match.group(1))
        layout_path = lineage_root / "storage_layout" / f"{contract}.json"
        entry = _find_layout_entry(layout_path, row.get("name"), slot)
        if entry is None:
            result.append(SymbolRuntimeBinding(
                symbol_id, xlir_type, domain, contract, None, ("pre", "post"), slot=slot,
                status=BindingStatus.MISSING, reason="storage_layout_entry_not_found",
            ))
            continue
        try:
            offset = int(entry.get("offset", 0))
        except (TypeError, ValueError):
            result.append(SymbolRuntimeBinding(
                symbol_id, xlir_type, domain, contract, None, ("pre", "post"), slot=slot,
                status=BindingStatus.INVALID, reason="storage_offset_not_integer",
            ))
            continue
        width = _WIDTHS[xlir_type]
        if offset + width > 32:
            result.append(SymbolRuntimeBinding(
                symbol_id, xlir_type, domain, contract, None, ("pre", "post"), slot=slot,
                offset_bytes=offset, status=BindingStatus.INVALID,
                reason="storage_packing_exceeds_word",
            ))
            continue
        getter = _find_getter(case_root, contract, str(row.get("name")))
        result.append(SymbolRuntimeBinding(
            symbol_id, xlir_type, domain, contract, f"storage:{contract}:{slot}:{offset}",
            ("pre", "post"), slot=slot, offset_bytes=offset, getter=getter,
            decode_rule=f"evm_storage_{xlir_type}", status=BindingStatus.BOUND,
            evidence={"layout_path": layout_path.relative_to(lineage_root).as_posix(), "label": row.get("name")},
        ))
    return tuple(sorted(result, key=lambda item: item.symbol_id))


def _build_action_bindings(
    lineage_root: Path,
    case_root: Path,
    symbols: Mapping[str, Any],
    harness: Mapping[str, Any],
) -> tuple[ActionRuntimeBinding, ...]:
    rows = symbols.get("stable_symbols")
    if not isinstance(rows, list):
        raise ValueError("symbols.json has no stable_symbols list")
    functions = [row for row in rows if isinstance(row, Mapping) and row.get("kind") == "abi_function"]
    workflow = harness.get("workflow_coverage")
    allowed = workflow.get("allowed_actions") if isinstance(workflow, Mapping) else None
    result: list[ActionRuntimeBinding] = []
    action_number = 0
    for role, actions in sorted(allowed.items()) if isinstance(allowed, Mapping) else ():
        if not isinstance(role, str) or not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, str) or not action.strip():
                continue
            action_number += 1
            action_id = f"action:{action_number:03d}"
            target, function_name = _split_action(action)
            matches = [row for row in functions if row.get("name") == function_name]
            if target:
                targeted = [row for row in matches if _contract_matches(str(row.get("contract", "")), target)]
                if targeted:
                    matches = targeted
            if len(matches) != 1:
                reason = "action_function_not_found" if not matches else "action_function_ambiguous"
                result.append(ActionRuntimeBinding(
                    action_id, action, role, _action_domain(role, harness),
                    target or None, None, None, None, None, "harness_declared", "harness_declared",
                    BindingStatus.MISSING if not matches else BindingStatus.AMBIGUOUS, reason,
                ))
                continue
            row = matches[0]
            signature = row.get("signature") if isinstance(row.get("signature"), str) else None
            selector = _find_selector(case_root, str(row.get("contract")), signature)
            selector_reason = None if selector else "selector_not_present_in_case_artifact"
            result.append(ActionRuntimeBinding(
                action_id, action, role, _action_domain(role, harness),
                str(row.get("contract")), str(row.get("symbol_id")), signature, selector,
                {"kind": "abi_signature", "signature": signature} if signature else None,
                "harness_declared", "harness_declared", BindingStatus.BOUND,
                selector_reason,
                {"source_symbol": row.get("symbol_id"), "target": target},
            ))
    return tuple(result)


def _runtime_missing_fields(
    runtime: CaseRuntimeSpec,
    actions: tuple[ActionRuntimeBinding, ...],
    deployment: Mapping[str, Any],
    harness: Mapping[str, Any],
) -> tuple[str, ...]:
    fields: set[str] = set()
    if not runtime.contract_addresses:
        fields.add("contract_addresses")
    if not runtime.actors:
        fields.add("actor_addresses")
    if not runtime.initial_state:
        fields.add("initial_state_descriptor")
    if any(action.signature is not None and action.selector is None for action in actions):
        fields.add("action_selectors")
    if not actions:
        fields.add("workflow_actions")
    if not isinstance(deployment.get("deployment_result"), Mapping):
        fields.add("deployment_receipt")
    if harness.get("source_backed") is not True:
        fields.add("source_backed_harness")
    return tuple(sorted(fields))


def _validate_runtime_artifacts(case_root: Path, build_manifest: Mapping[str, Any], paired_harness: Mapping[str, Any]) -> list[str]:
    diagnostics: list[str] = []
    if not isinstance(build_manifest.get("artifacts"), list) or not build_manifest["artifacts"]:
        diagnostics.append("build_manifest.artifacts_missing")
    test = paired_harness.get("test")
    if not isinstance(test, Mapping) or not isinstance(test.get("path"), str):
        diagnostics.append("paired_harness.test_missing")
    elif not (case_root / Path(test["path"])).is_file():
        diagnostics.append("paired_harness.test_file_missing")
    return diagnostics


def _unsupported_case(root: Path, lineage_id: str, case_id: str, missing: tuple[str, ...], diagnostics: tuple[str, ...] = ()) -> CaseRuntimeBindings:
    placeholder = "0" * 64
    runtime = CaseRuntimeSpec(
        case_id=case_id, lineage_id=lineage_id, instance_id=case_id,
        source_artifact_hash=placeholder, build_manifest_hash=placeholder,
        deployment_hash=placeholder, profile_hash=placeholder, compiler_hash=placeholder,
        source_domain="unknown_source", destination_domain="unknown_destination",
        runtime_mode="unknown", metadata={"runtime_binding": "unavailable"},
    )
    return CaseRuntimeBindings(runtime, (), (), missing, diagnostics)


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_field(metadata: Mapping[str, Any], field: str, fallback: object, fallback_field: str | None) -> str:
    value = metadata.get(field)
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        if isinstance(fallback, Mapping) and fallback_field and isinstance(fallback.get(fallback_field), str):
            value = fallback[fallback_field]
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field} is not a lowercase SHA-256 digest")
    return value


def _require_identity(metadata: Mapping[str, Any], lineage_id: str, case_id: str) -> None:
    if metadata.get("lineage_id") != lineage_id or metadata.get("instance_id") != case_id:
        raise ValueError("case metadata identity does not match its path")


def _nonempty(value: Mapping[str, Any] | None, field: str) -> str:
    item = value.get(field) if isinstance(value, Mapping) else None
    if not isinstance(item, str) or not item:
        raise ValueError(f"missing non-empty {field}")
    return item


def _unique_strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(sorted({item for item in value if isinstance(item, str) and item}))


def _flatten_actions(value: object) -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        return ()
    items: set[str] = set()
    for values in value.values():
        if isinstance(values, list):
            items.update(item for item in values if isinstance(item, str) and item)
    return tuple(sorted(items))


def _extract_addresses(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        if isinstance(key, str) and isinstance(item, str) and _HEX_ADDRESS_RE.fullmatch(item):
            result[key] = item
    for key, item in value.items():
        if isinstance(item, Mapping):
            for nested_key, address in _extract_addresses(item).items():
                result[f"{key}.{nested_key}"] = address
    return dict(sorted(result.items()))


def _find_layout_entry(path: Path, name: object, slot: int) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = _read_object(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    rows = data.get("storage")
    if not isinstance(rows, list):
        return None
    return next((row for row in rows if isinstance(row, Mapping) and row.get("label") == name and str(row.get("slot")) == str(slot)), None)


def _find_getter(case_root: Path, contract: str, name: str) -> str | None:
    for path in sorted((case_root / "runtime" / "artifacts").glob(f"{contract}.json")):
        try:
            data = _read_object(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        for row in data.get("abi", ()) if isinstance(data.get("abi"), list) else ():
            if isinstance(row, Mapping) and row.get("type") == "function" and row.get("name") == name and not row.get("inputs"):
                return f"{contract}.{name}()"
    return None


def _split_action(action: str) -> tuple[str | None, str]:
    normalized = action.split("->")[-1].strip()
    if "." in normalized:
        target, function = normalized.rsplit(".", 1)
        return target.strip(), function.strip()
    return None, normalized


def _contract_matches(contract: str, target: str) -> bool:
    return contract == target or contract.endswith(target) or target.endswith(contract)


def _action_domain(role: str, harness: Mapping[str, Any]) -> str:
    lower = role.lower()
    if any(token in lower for token in ("destination", "l2", "recipient", "relayer", "receiver", "nullifier", "node")):
        domain = harness.get("domain_pair", {})
        destination = domain.get("destination") if isinstance(domain, Mapping) else None
        if isinstance(destination, Mapping) and isinstance(destination.get("name"), str):
            return destination["name"]
    domain = harness.get("domain_pair", {})
    source = domain.get("source") if isinstance(domain, Mapping) else None
    if isinstance(source, Mapping) and isinstance(source.get("name"), str):
        return source["name"]
    return "unknown"


def _find_selector(case_root: Path, contract: str, signature: str | None) -> str | None:
    if not signature:
        return None
    path = case_root / "runtime" / "artifacts" / f"{contract}.json"
    if not path.is_file():
        return None
    try:
        data = _read_object(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    identifiers = data.get("methodIdentifiers")
    selector = identifiers.get(signature) if isinstance(identifiers, Mapping) else None
    if isinstance(selector, str) and re.fullmatch(r"[0-9a-fA-F]{8}", selector):
        return "0x" + selector.lower()
    return None


__all__ = [
    "ActionRuntimeBinding", "BindingStatus", "CaseRuntimeBindings", "RuntimeBindingMatrix",
    "SymbolRuntimeBinding", "build_runtime_binding_matrix", "load_case_runtime",
]
