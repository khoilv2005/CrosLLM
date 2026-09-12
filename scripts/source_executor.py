#!/usr/bin/env python3
"""Executable source-backed bounded search, witness check and replay adapter.

This is the first-party development adapter for the Across source harness.  It
does not inspect mutation patches, gold properties, trigger receipts, or any
other admission-only artifact.  The request contains a grounded XLIR
predicate; this adapter lowers the supported state-expression subset into a
candidate-specific Solidity test, then executes that test in the disposable
Foundry workspace supplied by ``SourceBackedVerificationExecutors``.

The search bound is deliberately explicit: one declared normal Across
deposit/fast-fill workflow.  This is an executable source-backed *bounded*
search, not a claim that a general EVM symbolic solver has been implemented.
Unsupported predicates, lineages, or workflows fail closed.

The command prints exactly one JSON object on stdout:

    python scripts/source_executor.py search --request REQUEST.json
    python scripts/source_executor.py witness --request REQUEST.json
    python scripts/source_executor.py replay --witness WITNESS.json --workspace DIR
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from crossllm.contracts.records import ReplayStatus, SearchStatus  # noqa: E402
from scripts.run_source_case_harness import (  # noqa: E402
    DEFAULT_IMAGE,
    run_harness,
)


ENGINE_ID = "source-foundry-bounded-v1"
PROFILE_ID = "across-normal-deposit-fast-fill-v1"
GENERATED_TEST_PREFIX = "CrossLLMCandidate_"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_GETTER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\(\)$")
_SAFE_SYMBOL = re.compile(r"^[A-Za-z0-9_.:-]+$")


class AdapterUnsupported(ValueError):
    """The first-party adapter cannot soundly execute this request."""


class AdapterInputError(ValueError):
    """The request is malformed or violates the execution contract."""


@dataclass(frozen=True, slots=True)
class PreparedRequest:
    request: dict[str, Any]
    workspace: Path
    predicate: Mapping[str, Any]
    bindings: dict[tuple[str, str], Mapping[str, Any]]
    pre_reads: tuple[str, ...]
    test_path: str
    predicate_hash: str


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    status: str
    reason: str | None
    exit_code: int | None
    stdout_hash: str
    stderr_hash: str
    test_path: str
    test_name: str

    def as_dict(self) -> dict[str, object]:
        return {
            "engine_id": ENGINE_ID,
            "status": self.status,
            "reason": self.reason,
            "exit_code": self.exit_code,
            "stdout_sha256": self.stdout_hash,
            "stderr_sha256": self.stderr_hash,
            "test_path": self.test_path,
            "test_name": self.test_name,
        }


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise AdapterInputError(f"json_input_error:{error}") from error
    if not isinstance(value, dict):
        raise AdapterInputError("json_input_must_be_object")
    return value


def _request_from_path(path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    payload = _load_json(path)
    witness = payload.get("witness") if isinstance(payload.get("witness"), dict) else None
    runtime_request = payload.get("runtime_request")
    if isinstance(runtime_request, dict):
        return runtime_request, witness
    return payload, witness


def _require_text(value: Mapping[str, Any], field: str, label: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise AdapterInputError(f"{label}_missing_{field}")
    return item


def _validate_workspace(request: Mapping[str, Any], workspace: Path | None = None) -> Path:
    raw = workspace or Path(_require_text(request, "source_workspace", "request"))
    resolved = raw.resolve()
    if not resolved.is_dir():
        raise AdapterInputError(f"source_workspace_missing:{resolved}")
    identity = request.get("source_case_identity")
    if not isinstance(identity, Mapping):
        raise AdapterInputError("source_case_identity_missing")
    if identity.get("lineage_id") != request.get("lineage_id"):
        raise AdapterInputError("source_case_identity_lineage_mismatch")
    if identity.get("case_id") != request.get("case_id"):
        raise AdapterInputError("source_case_identity_case_mismatch")
    if not (resolved / "test").is_dir():
        raise AdapterInputError("source_workspace_test_directory_missing")
    return resolved


def _profile_for(request: Mapping[str, Any]) -> None:
    if request.get("lineage_id") != "across":
        raise AdapterUnsupported("lineage_profile_not_implemented")
    runtime = request.get("runtime")
    if not isinstance(runtime, Mapping) or runtime.get("runtime_mode") != "source_backed_local_evm":
        raise AdapterUnsupported("runtime_mode_not_source_backed_local_evm")
    metadata = runtime.get("metadata")
    if not isinstance(metadata, Mapping) or metadata.get("source_backed") is not True:
        raise AdapterUnsupported("runtime_not_marked_source_backed")
    if metadata.get("test_contract") != "AcrossSourceBackedHarnessTest":
        raise AdapterUnsupported("across_test_contract_profile_mismatch")


def _collect_symbols(node: object, output: set[tuple[str, str]]) -> None:
    if not isinstance(node, Mapping):
        return
    if node.get("kind") == "symbol":
        symbol_id = node.get("symbol_id")
        state = node.get("state")
        if not isinstance(symbol_id, str) or not isinstance(state, str):
            raise AdapterInputError("symbol_reference_missing_identity")
        output.add((symbol_id, state))
    for child in node.values():
        if isinstance(child, Mapping):
            _collect_symbols(child, output)
        elif isinstance(child, list):
            for item in child:
                _collect_symbols(item, output)


def _prepare(request: dict[str, Any], workspace: Path | None = None) -> PreparedRequest:
    _profile_for(request)
    actual_workspace = _validate_workspace(request, workspace)
    predicate = request.get("predicate")
    if not isinstance(predicate, Mapping):
        raise AdapterInputError("predicate_missing")
    if predicate.get("kind") == "temporal":
        raise AdapterUnsupported("temporal_predicate_requires_trace_backend")
    if predicate.get("kind") == "quantifier":
        raise AdapterUnsupported("quantifier_requires_symbolic_backend")
    symbols: set[tuple[str, str]] = set()
    _collect_symbols(predicate, symbols)
    if not symbols:
        # A literal predicate is still candidate-specific and useful for a
        # pipeline smoke test, but it must not silently stand in for missing
        # symbol bindings in a non-literal candidate.
        if predicate.get("kind") != "literal":
            raise AdapterInputError("predicate_has_no_resolvable_symbols")
    raw_bindings = request.get("symbol_bindings")
    if not isinstance(raw_bindings, list):
        raise AdapterInputError("symbol_bindings_missing")
    bindings: dict[tuple[str, str], Mapping[str, Any]] = {}
    for binding in raw_bindings:
        if not isinstance(binding, Mapping):
            raise AdapterInputError("symbol_binding_not_object")
        symbol_id = binding.get("symbol_id")
        if isinstance(symbol_id, str):
            for state in ("pre", "post"):
                if (symbol_id, state) in symbols:
                    bindings[(symbol_id, state)] = binding
    missing = sorted(symbol for symbol in symbols if symbol not in bindings)
    if missing:
        raise AdapterUnsupported("symbol_binding_not_available:" + ",".join(f"{a}|{b}" for a, b in missing))
    pre_reads = tuple(sorted({symbol_id for symbol_id, state in symbols if state == "pre"}))
    predicate_hash = _digest(predicate)
    test_name = "test_candidate_search"
    test_path = f"test/{GENERATED_TEST_PREFIX}{predicate_hash[:24]}.t.sol"
    return PreparedRequest(request, actual_workspace, predicate, bindings, pre_reads, test_path, predicate_hash)


def _target_for(binding: Mapping[str, Any], request: Mapping[str, Any]) -> str:
    domain = binding.get("domain")
    runtime = request.get("runtime")
    destination = runtime.get("destination_domain") if isinstance(runtime, Mapping) else None
    return "destinationPool" if domain == destination else "sourcePool"


def _storage_expression(binding: Mapping[str, Any], target: str) -> str:
    slot = binding.get("slot")
    offset = binding.get("offset_bytes", 0)
    symbol_type = binding.get("symbol_type")
    if not isinstance(slot, int) or isinstance(slot, bool) or slot < 0:
        raise AdapterUnsupported("storage_binding_missing_slot")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0 or offset > 31:
        raise AdapterUnsupported("storage_binding_invalid_offset")
    if symbol_type not in {"bool", "uint256", "int256", "address", "bytes32"}:
        raise AdapterUnsupported("storage_type_not_supported_by_across_adapter")
    raw = f"crossllmVm.load(address({target}), bytes32(uint256({slot})))"
    if symbol_type == "bool":
        return f"((uint256({raw}) >> {offset * 8}) & 1) != 0"
    if symbol_type == "uint256":
        return f"uint256({raw})"
    if symbol_type == "int256":
        return f"int256(uint256({raw}))"
    if symbol_type == "address":
        return f"address(uint160(uint256({raw})))"
    return f"bytes32({raw})"


def _getter_expression(binding: Mapping[str, Any], target: str) -> str | None:
    getter = binding.get("getter")
    if not isinstance(getter, str) or not getter:
        return None
    name = getter.rsplit(".", 1)[-1]
    if not _SAFE_GETTER.fullmatch(name):
        raise AdapterUnsupported("getter_name_not_safe")
    if binding.get("symbol_type") not in {"bool", "address", "uint256", "int256", "bytes32"}:
        raise AdapterUnsupported("getter_type_not_supported")
    return f"{target}.{name}"


def _value_expression(binding: Mapping[str, Any], request: Mapping[str, Any]) -> str:
    target = _target_for(binding, request)
    getter = _getter_expression(binding, target)
    return getter if getter is not None else _storage_expression(binding, target)


def _literal_expression(node: Mapping[str, Any]) -> str:
    value_type = node.get("type")
    value = node.get("value")
    if value_type == "bool" and isinstance(value, bool):
        return "true" if value else "false"
    if value_type in {"uint256", "int256"} and isinstance(value, int) and not isinstance(value, bool):
        if value_type == "uint256" and value < 0:
            raise AdapterUnsupported("negative_uint_literal")
        return str(value)
    if value_type == "address" and isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", value):
        return f"address({value})"
    if value_type == "bytes32" and isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{64}", value):
        return value
    raise AdapterUnsupported("literal_not_supported_by_solidity_lowering")


def _expression(node: Mapping[str, Any], prepared: PreparedRequest, state_override: str | None = None) -> str:
    kind = node.get("kind")
    if kind == "literal":
        return _literal_expression(node)
    if kind == "symbol":
        symbol_id = node.get("symbol_id")
        state = state_override or node.get("state")
        if not isinstance(symbol_id, str) or not isinstance(state, str) or state not in {"pre", "post"}:
            raise AdapterUnsupported("symbol_state_not_pre_or_post")
        binding = prepared.bindings.get((symbol_id, state)) or prepared.bindings.get((symbol_id, "post"))
        if binding is None:
            raise AdapterUnsupported(f"symbol_binding_missing:{symbol_id}|{state}")
        if state == "pre":
            name = f"pre_{_digest(symbol_id)[:16]}"
            return name
        return _value_expression(binding, prepared.request)
    if kind == "unary":
        operator = node.get("operator")
        operand = node.get("operand")
        if not isinstance(operand, Mapping):
            raise AdapterInputError("unary_operand_missing")
        expression = _expression(operand, prepared, state_override)
        if operator == "not":
            return f"(!({expression}))"
        if operator == "neg":
            return f"(-({expression}))"
        if operator == "bitnot":
            return f"~({expression})"
        raise AdapterUnsupported(f"unary_operator_not_supported:{operator}")
    if kind == "binary":
        left = node.get("left")
        right = node.get("right")
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            raise AdapterInputError("binary_operands_missing")
        operator = node.get("operator")
        if operator == "implies":
            return f"(!({_expression(left, prepared, state_override)}) || ({_expression(right, prepared, state_override)}))"
        solidity_operator = {
            "and": "&&", "or": "||", "eq": "==", "neq": "!=",
            "ge": ">=", "le": "<=", "gt": ">", "lt": "<",
            "add": "+", "sub": "-", "mul": "*", "div": "/", "mod": "%",
            "band": "&", "bor": "|", "bxor": "^", "shl": "<<", "shr": ">>",
        }.get(operator)
        if solidity_operator is None:
            raise AdapterUnsupported(f"binary_operator_not_supported:{operator}")
        return f"(({_expression(left, prepared, state_override)}) {solidity_operator} ({_expression(right, prepared, state_override)}))"
    if kind == "quantifier":
        raise AdapterUnsupported("quantifier_requires_symbolic_backend")
    raise AdapterUnsupported(f"expression_kind_not_supported:{kind}")


def _pre_declarations(prepared: PreparedRequest) -> list[str]:
    declarations: list[str] = []
    for symbol_id in prepared.pre_reads:
        binding = prepared.bindings.get((symbol_id, "pre")) or prepared.bindings.get((symbol_id, "post"))
        if binding is None:
            raise AdapterUnsupported(f"pre_binding_missing:{symbol_id}")
        symbol_type = binding.get("symbol_type")
        if symbol_type not in {"bool", "uint256", "int256", "address", "bytes32"}:
            raise AdapterUnsupported("pre_state_type_not_supported")
        name = f"pre_{_digest(symbol_id)[:16]}"
        declaration = f"{symbol_type} {name} = {_value_expression(binding, prepared.request)};"
        declarations.append(declaration)
    return declarations


def _candidate_source(prepared: PreparedRequest) -> str:
    predicate = _expression(prepared.predicate, prepared)
    pre = _pre_declarations(prepared)
    pre_block = "\n        ".join(pre)
    if pre_block:
        pre_block += "\n        "
    return f'''// SPDX-License-Identifier: BUSL-1.1
pragma solidity 0.8.30;

import "./AcrossSourceBackedHarnessTest.t.sol";

interface CrossLLMStorageVm {{
    function load(address target, bytes32 slot) external view returns (bytes32);
}}

contract CrossLLMCandidate_{prepared.predicate_hash[:24]} is AcrossSourceBackedHarnessTest {{
    CrossLLMStorageVm internal constant crossllmVm = CrossLLMStorageVm(
        address(uint160(uint256(keccak256("hevm cheat code"))))
    );

    function {"test_candidate_search"}() public {{
        {pre_block}test_normal_source_backed_deposit_and_fast_fill();
        // The test passes exactly when the grounded candidate predicate is
        // false after the source-backed workflow: this is the SAT witness.
        require(!({predicate}), "CANDIDATE_HOLDS");
    }}
}}
'''


def _write_candidate_test(prepared: PreparedRequest) -> None:
    path = prepared.workspace / prepared.test_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_candidate_source(prepared), encoding="utf-8")


def _contains_marker(value: object, marker: str) -> bool:
    if isinstance(value, str):
        return marker in value
    if isinstance(value, Mapping):
        return any(_contains_marker(item, marker) for item in value.values())
    if isinstance(value, list):
        return any(_contains_marker(item, marker) for item in value)
    return False


def _parse_foundry_json(raw: bytes) -> object | None:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char not in "{[":
                continue
            try:
                value, end = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if not text[index + end :].strip():
                return value
    return None


def _execute(prepared: PreparedRequest) -> tuple[ExecutionReceipt, bytes, bytes]:
    _write_candidate_test(prepared)
    image = os.environ.get("CROSSLLM_FOUNDRY_IMAGE", DEFAULT_IMAGE)
    compiler_volume = os.environ.get("CROSSLLM_COMPILER_VOLUME") or None
    timeout = float(os.environ.get("CROSSLLM_SOURCE_PHASE_TIMEOUT_SECONDS", "300"))
    if timeout <= 0:
        raise AdapterInputError("source_phase_timeout_must_be_positive")
    status, exit_code, stdout, stderr, reason = run_harness(
        prepared.workspace,
        image=image,
        test_path=prepared.test_path,
        match_test="test_candidate_search",
        timeout_seconds=timeout,
        compiler_volume=compiler_volume,
    )
    receipt = ExecutionReceipt(
        status=status,
        reason=reason,
        exit_code=exit_code,
        stdout_hash=hashlib.sha256(stdout).hexdigest(),
        stderr_hash=hashlib.sha256(stderr).hexdigest(),
        test_path=prepared.test_path,
        test_name="test_candidate_search",
    )
    return receipt, stdout, stderr


def _workflow_description(prepared: PreparedRequest) -> dict[str, object]:
    actions = prepared.request.get("actions")
    if not isinstance(actions, list):
        raise AdapterInputError("actions_missing")
    by_id = {item.get("action_id"): item for item in actions if isinstance(item, Mapping)}
    required = ("action:001", "action:003")
    for action_id in required:
        action = by_id.get(action_id)
        if not isinstance(action, Mapping) or action.get("executable") is not True:
            raise AdapterUnsupported(f"across_workflow_action_unavailable:{action_id}")
    return {
        "profile_id": PROFILE_ID,
        "bound_actions": list(required),
        "workflow": [
            "setUp",
            "SpokePool.depositV3 via _deposit(0,address(0))",
            "SpokePool.fillRelay via test_normal_source_backed_deposit_and_fast_fill",
        ],
        "bound_observations": list(prepared.request.get("observation_points", [])),
        "search_bound": "one deterministic normal deposit/fast-fill trace",
    }


def _witness(prepared: PreparedRequest, receipt: ExecutionReceipt) -> dict[str, Any]:
    workflow = _workflow_description(prepared)
    runtime = prepared.request.get("runtime")
    runtime_hash = _require_text(prepared.request, "runtime_hash", "request")
    artifact_hash = _require_text(prepared.request, "artifact_hash", "request")
    deployment_hash = _require_text(prepared.request, "deployment_hash", "request")
    canonical_hash = _require_text(prepared.request, "canonical_ast_hash", "request")
    initial_state_hash = _require_text(prepared.request, "initial_state_hash", "request")
    actions = prepared.request.get("actions")
    assert isinstance(actions, list)
    by_id = {item.get("action_id"): item for item in actions if isinstance(item, Mapping)}
    witness_actions: list[dict[str, str]] = []
    for action_id, caller in (("action:001", "user"), ("action:003", "relayer")):
        action = by_id[action_id]
        witness_actions.append({
            "action_id": action_id,
            "caller": caller,
            "caller_role": str(action["caller_role"]),
            "calldata": str(action["selector"]),
            "domain": str(action["domain"]),
            "contract": str(action["contract"]),
            "selector": str(action["selector"]),
            "executable": True,
        })
    trace_material = {
        "schema_version": 1,
        "engine_id": ENGINE_ID,
        "profile_id": PROFILE_ID,
        "runtime_hash": runtime_hash,
        "canonical_ast_hash": canonical_hash,
        "predicate_hash": prepared.predicate_hash,
        "workflow": workflow,
        "actions": witness_actions,
        "symbol_bindings": [dict(binding) for binding in prepared.bindings.values()],
    }
    trace_hash = _digest(trace_material)
    identity = prepared.request.get("source_case_identity")
    return {
        "schema_version": 1,
        "record_type": "source_backed_witness",
        "witness_id": f"witness:{trace_hash[:24]}",
        "query_id": f"query:{canonical_hash[:24]}",
        "lineage_id": prepared.request["lineage_id"],
        "case_id": prepared.request["case_id"],
        "instance_id": prepared.request["instance_id"],
        "profile_id": PROFILE_ID,
        "engine_id": ENGINE_ID,
        "runtime_hash": runtime_hash,
        "artifact_hash": artifact_hash,
        "deployment_hash": deployment_hash,
        "canonical_ast_hash": canonical_hash,
        "initial_state_hash": initial_state_hash,
        "trace_hash": trace_hash,
        "actions": witness_actions,
        "domains": [
            str(prepared.request["source_domain"]),
            str(prepared.request["destination_domain"]),
        ],
        "observations": list(prepared.request.get("observation_points", [])),
        "source_case_identity": dict(identity) if isinstance(identity, Mapping) else None,
        "predicate": dict(prepared.predicate),
        "predicate_lowering": prepared.request.get("predicate_lowering"),
        "symbol_bindings": [dict(binding) for binding in prepared.bindings.values()],
        "runtime": dict(runtime) if isinstance(runtime, Mapping) else None,
        "workflow": workflow,
        "execution_receipt": receipt.as_dict(),
    }


def _search(request_path: Path) -> dict[str, object]:
    request, _ = _request_from_path(request_path)
    try:
        prepared = _prepare(request)
        receipt, stdout, stderr = _execute(prepared)
    except AdapterUnsupported as error:
        return {
            "schema_version": 1,
            "record_type": "source_backed_search_result",
            "status": SearchStatus.UNSUPPORTED.value,
            "complete": False,
            "candidate_violation": False,
            "engine_id": ENGINE_ID,
            "profile_id": PROFILE_ID,
            "reason": str(error),
        }
    except AdapterInputError as error:
        return {
            "schema_version": 1,
            "record_type": "source_backed_search_result",
            "status": SearchStatus.UNKNOWN.value,
            "complete": False,
            "candidate_violation": False,
            "engine_id": ENGINE_ID,
            "reason": str(error),
        }
    parsed = _parse_foundry_json(stdout)
    receipt_dict = receipt.as_dict()
    if receipt.status == "timeout":
        return {"schema_version": 1, "record_type": "source_backed_search_result", "status": SearchStatus.TIMEOUT.value, "complete": False, "candidate_violation": False, "engine_id": ENGINE_ID, "profile_id": PROFILE_ID, "reason": receipt.reason, "execution_receipt": receipt_dict}
    if receipt.status == "tool_error":
        return {"schema_version": 1, "record_type": "source_backed_search_result", "status": SearchStatus.UNSUPPORTED.value, "complete": False, "candidate_violation": False, "engine_id": ENGINE_ID, "profile_id": PROFILE_ID, "reason": receipt.reason, "execution_receipt": receipt_dict}
    if receipt.status == "pass":
        witness = _witness(prepared, receipt)
        return {
            "schema_version": 1,
            "record_type": "source_backed_search_result",
            "status": SearchStatus.SAT.value,
            "complete": True,
            "candidate_violation": True,
            "engine_id": ENGINE_ID,
            "engine_semantics": "candidate-specific bounded source execution; no gold oracle",
            "profile_id": PROFILE_ID,
            "search_bound": _workflow_description(prepared),
            "execution_receipt": receipt_dict,
            "foundry_result": parsed,
            "witness": witness,
        }
    if _contains_marker(parsed, "CANDIDATE_HOLDS") or b"CANDIDATE_HOLDS" in stdout or b"CANDIDATE_HOLDS" in stderr:
        return {
            "schema_version": 1,
            "record_type": "source_backed_search_result",
            "status": SearchStatus.BOUNDED_UNSAT.value,
            "complete": True,
            "candidate_violation": False,
            "engine_id": ENGINE_ID,
            "engine_semantics": "candidate-specific bounded source execution; no gold oracle",
            "profile_id": PROFILE_ID,
            "reason": "predicate_holds_on_declared_workflow",
            "search_bound": _workflow_description(prepared),
            "execution_receipt": receipt_dict,
            "foundry_result": parsed,
        }
    return {
        "schema_version": 1,
        "record_type": "source_backed_search_result",
        "status": SearchStatus.CRASH.value,
        "complete": False,
        "candidate_violation": False,
        "engine_id": ENGINE_ID,
        "profile_id": PROFILE_ID,
        "reason": receipt.reason or "foundry_execution_failed",
        "execution_receipt": receipt_dict,
        "foundry_result": parsed,
    }


def _witness_check(request_path: Path) -> dict[str, object]:
    request, witness = _request_from_path(request_path)
    if witness is None:
        return {"schema_version": 1, "record_type": "source_backed_witness_check", "status": ReplayStatus.UNKNOWN.value, "reason": "witness_missing"}
    try:
        prepared = _prepare(request)
        receipt, stdout, stderr = _execute(prepared)
    except (AdapterUnsupported, AdapterInputError) as error:
        return {"schema_version": 1, "record_type": "source_backed_witness_check", "status": ReplayStatus.UNSUPPORTED.value, "reason": str(error)}
    expected = _witness(prepared, receipt)
    receipt_dict = receipt.as_dict()
    if witness.get("trace_hash") != expected["trace_hash"]:
        return {"schema_version": 1, "record_type": "source_backed_witness_check", "status": ReplayStatus.FAIL.value, "reason": "witness_trace_hash_mismatch", "trace_hash": expected["trace_hash"], "execution_receipt": receipt_dict}
    if receipt.status == "pass":
        return {"schema_version": 1, "record_type": "source_backed_witness_check", "status": ReplayStatus.PASS.value, "trace_hash": expected["trace_hash"], "candidate_violation": True, "property_holds": False, "engine_id": ENGINE_ID, "profile_id": PROFILE_ID, "execution_receipt": receipt_dict}
    if receipt.status == "timeout":
        return {"schema_version": 1, "record_type": "source_backed_witness_check", "status": ReplayStatus.UNKNOWN.value, "reason": receipt.reason, "trace_hash": expected["trace_hash"], "execution_receipt": receipt_dict}
    return {"schema_version": 1, "record_type": "source_backed_witness_check", "status": ReplayStatus.FAIL.value, "reason": receipt.reason or "witness_does_not_demonstrate_violation", "trace_hash": expected["trace_hash"], "candidate_violation": False, "property_holds": True, "engine_id": ENGINE_ID, "profile_id": PROFILE_ID, "execution_receipt": receipt_dict}


def _replay(witness_path: Path, workspace: Path) -> dict[str, object]:
    witness = _load_json(witness_path)
    predicate = witness.get("predicate")
    runtime = witness.get("runtime")
    if not isinstance(predicate, Mapping) or not isinstance(runtime, Mapping):
        return {"schema_version": 1, "record_type": "source_backed_independent_replay", "status": ReplayStatus.UNKNOWN.value, "reason": "witness_missing_replay_request"}
    request: dict[str, Any] = {
        "lineage_id": witness.get("lineage_id"),
        "case_id": witness.get("case_id"),
        "instance_id": witness.get("instance_id"),
        "runtime": runtime,
        "runtime_hash": witness.get("runtime_hash"),
        "artifact_hash": witness.get("artifact_hash"),
        "deployment_hash": witness.get("deployment_hash"),
        "canonical_ast_hash": witness.get("canonical_ast_hash"),
        "initial_state_hash": witness.get("initial_state_hash"),
        "predicate": predicate,
        "predicate_lowering": witness.get("predicate_lowering"),
        "symbol_bindings": witness.get("symbol_bindings", []),
        "actions": witness.get("actions", []),
        "observation_points": witness.get("observations", []),
        "source_domain": runtime.get("source_domain"),
        "destination_domain": runtime.get("destination_domain"),
        "source_case_identity": witness.get("source_case_identity"),
        "source_workspace": str(workspace),
    }
    # Search witnesses retain the complete grounded bindings in the current
    # schema.  Refuse to replay an older/incomplete witness rather than
    # falling back to a guessed getter or a paired fixture.
    if not isinstance(request["symbol_bindings"], list) or not request["symbol_bindings"]:
        return {"schema_version": 1, "record_type": "source_backed_independent_replay", "status": ReplayStatus.UNKNOWN.value, "reason": "witness_missing_symbol_bindings"}
    try:
        prepared = _prepare(request, workspace)
        receipt, stdout, stderr = _execute(prepared)
        expected = _witness(prepared, receipt)
    except (AdapterUnsupported, AdapterInputError) as error:
        return {"schema_version": 1, "record_type": "source_backed_independent_replay", "status": ReplayStatus.UNSUPPORTED.value, "reason": str(error)}
    receipt_dict = receipt.as_dict()
    if expected["trace_hash"] != witness.get("trace_hash"):
        return {"schema_version": 1, "record_type": "source_backed_independent_replay", "status": ReplayStatus.FAIL.value, "reason": "replay_trace_hash_mismatch", "trace_hash": expected["trace_hash"], "property_holds": None, "security_relevance": None, "execution_receipt": receipt_dict}
    if receipt.status == "pass":
        return {"schema_version": 1, "record_type": "source_backed_independent_replay", "status": ReplayStatus.PASS.value, "trace_hash": expected["trace_hash"], "property_holds": False, "security_relevance": True, "engine_id": ENGINE_ID, "profile_id": PROFILE_ID, "execution_receipt": receipt_dict}
    if receipt.status == "timeout":
        return {"schema_version": 1, "record_type": "source_backed_independent_replay", "status": ReplayStatus.UNKNOWN.value, "reason": receipt.reason, "trace_hash": expected["trace_hash"], "property_holds": None, "security_relevance": None, "execution_receipt": receipt_dict}
    return {"schema_version": 1, "record_type": "source_backed_independent_replay", "status": ReplayStatus.FAIL.value, "reason": receipt.reason or "replay_did_not_demonstrate_violation", "trace_hash": expected["trace_hash"], "property_holds": True, "security_relevance": True, "execution_receipt": receipt_dict}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    search = subparsers.add_parser("search")
    search.add_argument("--request", type=Path, required=True)
    witness = subparsers.add_parser("witness")
    witness.add_argument("--request", type=Path, required=True)
    # The shared executor contract also materializes a separate witness file.
    # The request envelope already contains the same witness, but accepting
    # this path keeps the first-party command compatible with that contract.
    witness.add_argument("--witness", type=Path, default=None)
    replay = subparsers.add_parser("replay")
    replay.add_argument("--witness", type=Path, required=True)
    replay.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "search":
            output = _search(args.request)
        elif args.command == "witness":
            output = _witness_check(args.request)
        else:
            output = _replay(args.witness, args.workspace)
    except (OSError, ValueError) as error:
        output = {
            "schema_version": 1,
            "record_type": f"source_backed_{args.command}_result",
            "status": SearchStatus.UNKNOWN.value if args.command == "search" else ReplayStatus.UNKNOWN.value,
            "complete": False if args.command == "search" else None,
            "reason": f"adapter_exception:{type(error).__name__}:{error}",
            "engine_id": ENGINE_ID,
        }
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
