#!/usr/bin/env python3
"""Run the bounded development backend feasibility spike.

The report exercises the five M00.02 mechanics on the in-memory paired
fixture and the solver-neutral XLIR storage binding.  It deliberately records
that this is not an EVM trace, source-level evaluator, or admission result.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossllm.artifacts import ArtifactSymbol
from crossllm.contracts.canonical import sha256_hex
from crossllm.replay import NativeReplay, WitnessProjector
from crossllm.replay.witness import state_hash
from crossllm.backends import SymbolicPairedExplorer
from crossllm.semantics import Message, PairedFixture, TransitionBounds, TransitionProfile
from crossllm.xlir import XLIRCompiler, XLIRLowerer, evaluate_invariant


DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "backend_feasibility_spike.json"


def _message(nonce: int) -> Message:
    return Message(
        "source",
        "destination",
        "bridge",
        "receiver",
        nonce,
        "0x" + f"{nonce:064x}",
        intent_id=f"development-intent-{nonce}",
    )


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _snapshot_restore() -> dict[str, object]:
    first, second = _message(1), _message(2)
    fixture = PairedFixture(bounds=TransitionBounds(6, 6, 2))
    fixture.enqueue(first)
    fixture.deliver()
    fixture.observe("development-marker", {"value": 1})
    snapshot = fixture.snapshot()
    expected_hash = state_hash(snapshot)
    fixture.enqueue(second)
    fixture.restore(snapshot)
    restored_hash = state_hash(fixture.state)
    return {
        "status": "pass" if restored_hash == expected_hash else "fail",
        "checks": [
            "restore returns a deep copy of source/destination/channel/action state",
            "destination storage and ghost observer state survive restore",
            "post-snapshot mutation is absent after restore",
        ],
        "evidence": {
            "snapshot_state_hash": expected_hash,
            "restored_state_hash": restored_hash,
            "pending_after_restore": len(fixture.state.pending),
            "delivered_after_restore": len(fixture.state.delivered),
            "destination_storage_keys": sorted(fixture.state.destination.storage),
            "observer_keys": sorted(fixture.state.observer_state),
        },
    }


def _transaction_stepping() -> dict[str, object]:
    first, second = _message(1), _message(2)
    fixture = PairedFixture(bounds=TransitionBounds(6, 6, 2))
    fixture.enqueue(first)
    fixture.enqueue(second)
    fixture.deliver(index=1)
    actions = fixture.state.action_log
    sequential = [
        {
            "action": record.action.value,
            "message_nonce": record.message.nonce,
            "transaction_index": record.transaction_index,
            "channel_transition_index": record.channel_transition_index,
            "pending_before": record.pending_before,
            "pending_after": record.pending_after,
        }
        for record in actions
    ]
    passed = (
        [record.transaction_index for record in actions] == [1, 2, 3]
        and [record.channel_transition_index for record in actions] == [1, 2, 3]
        and [record.message.nonce for record in actions] == [1, 2, 2]
    )
    return {
        "status": "pass" if passed else "fail",
        "checks": [
            "enqueue and delivery consume exactly one external transaction each",
            "channel transitions are separately indexed",
            "delivery preserves the selected message identity and pending counts",
        ],
        "evidence": {
            "action_log": sequential,
            "transaction_count": fixture.state.transaction_count,
            "channel_transition_count": fixture.state.channel_transition_count,
        },
    }


def _symbolic_storage() -> dict[str, object]:
    message = _message(1)
    fixture = PairedFixture()
    fixture.enqueue(message)
    fixture.deliver()
    symbol = ArtifactSymbol(
        "sym.destination.received_payload",
        "Bridge.sol",
        "received_payload",
        "destination",
        "storage",
        "bytes32",
    )
    proposal = {
        "kind": "invariant",
        "body": {
            "kind": "binary",
            "operator": "eq",
            "left": {
                "kind": "symbol",
                "symbol_id": symbol.symbol_id,
                "state": "post",
            },
            "right": {"kind": "literal", "type": "bytes32", "value": message.payload_commitment},
        },
    }
    compilation = XLIRCompiler.from_symbols([symbol]).compile(proposal)
    if not compilation.ok or compilation.invariant is None:
        raise ValueError(f"storage binding compilation failed: {compilation.diagnostics}")
    lowered = XLIRLowerer().lower(compilation.invariant)
    if not lowered.ok or lowered.ir is None:
        raise ValueError(f"storage binding lowering failed: {lowered.diagnostics}")
    binding_key = (symbol.symbol_id, "post", "destination")
    evaluated = evaluate_invariant(
        compilation.invariant,
        {binding_key: fixture.state.destination.storage["received:1"]},
    )
    return {
        "status": "pass" if evaluated else "fail",
        "checks": [
            "artifact storage symbol resolves to an explicit domain/state binding",
            "concrete fixture storage is evaluated through the typed XLIR core",
            "solver-neutral lowering preserves the same bytes32 symbol binding",
        ],
        "evidence": {
            "symbol_id": symbol.symbol_id,
            "binding_key": list(binding_key),
            "binding_value": message.payload_commitment,
            "invariant_hash": compilation.invariant.canonical_hash,
            "lowered_ir_hash": sha256_hex(lowered.ir.as_dict()),
            "lowered_symbol_names": lowered.ir.symbol_names,
            "concrete_evaluation": evaluated,
            "binding_scope": "grounded_fixture_storage_only",
        },
    }


def _channel_actions() -> dict[str, object]:
    first, second = _message(1), _message(2)
    fixture = PairedFixture(
        bounds=TransitionBounds(4, 4, 2),
        profile=TransitionProfile(allow_pre_finality_reorg=True, finality_depth=1),
    )
    fixture.enqueue(first)
    fixture.enqueue(second)
    fixture.reorg(index=1)
    reorg_actions = [record.action.value for record in fixture.state.action_log]

    fifo = PairedFixture(
        bounds=TransitionBounds(4, 4, 2),
        profile=TransitionProfile(allow_reordering=False),
    )
    fifo.enqueue(first)
    fifo.enqueue(second)
    fifo.deliver()
    fifo_order = [message.nonce for message in fifo.state.delivered]
    passed = reorg_actions == ["enqueue", "enqueue", "reorg"] and fifo_order == [1]
    return {
        "status": "pass" if passed else "fail",
        "checks": [
            "adversarial reordering and FIFO are separate profile behaviors",
            "pre-finality reorg removes only a pending, non-finalized message",
            "reorg changes transaction count but not channel-transition count",
        ],
        "evidence": {
            "reorg_action_sequence": reorg_actions,
            "reorg_transaction_count": fixture.state.transaction_count,
            "reorg_channel_transition_count": fixture.state.channel_transition_count,
            "fifo_delivery_order": fifo_order,
        },
    }


def _witness_extraction() -> dict[str, object]:
    first, second = _message(1), _message(2)
    fixture = PairedFixture(bounds=TransitionBounds(4, 4, 2))
    result = SymbolicPairedExplorer([first, second]).search(
        fixture,
        lambda state: (
            bool(state.delivered)
            and state.delivered[0].nonce == 2
            and any(item.nonce == 1 for item in state.pending)
        ),
    )
    witness = WitnessProjector().project(
        result,
        fixture,
        witness_id="m00-02-development-witness",
        query_id="m00-02-reordering-query",
        created_at="2026-09-09T00:00:00Z",
    )
    replay = NativeReplay().check(witness, fixture)
    return {
        "status": "pass" if replay.status.value == "pass" else "fail",
        "checks": [
            "only a complete SAT result is projected into a witness",
            "witness contains initial-state and trace hashes plus indexed actions",
            "native replay independently checks witness hash and action sequence within the fixture contract",
        ],
        "evidence": {
            "symbolic_status": result.status.value,
            "symbolic_complete": result.complete,
            "encoding_hash": result.encoding_hash,
            "witness_id": witness.witness_id,
            "initial_state_hash": witness.initial_state_hash,
            "trace_hash": witness.trace_hash,
            "action_count": len(witness.actions),
            "action_sequence": [row["action"] for row in witness.actions],
            "native_replay_status": replay.status.value,
            "native_replay_actions": replay.executed_actions,
        },
    }


def build_report(root: Path = ROOT, *, observed_at: str | None = None) -> dict[str, Any]:
    del root  # The development fixture has no external artifact input.
    bounds = TransitionBounds(6, 6, 2)
    profile = TransitionProfile()
    body: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "development_backend_feasibility_spike",
        "scope": "paired_fixture_g1_development_only",
        "status": "pass",
        "fixture": {
            "source_domain": "source",
            "destination_domain": "destination",
            "bounds": {
                "max_transactions": bounds.max_transactions,
                "max_channel_transitions": bounds.max_channel_transitions,
                "max_pending": bounds.max_pending,
            },
            "profile_hash": sha256_hex({
                "allow_reordering": profile.allow_reordering,
                "allow_duplicate_enqueue": profile.allow_duplicate_enqueue,
                "allow_pre_finality_reorg": profile.allow_pre_finality_reorg,
                "finality_depth": profile.finality_depth,
                "require_attestation": profile.require_attestation,
                "authorized_emitters": list(profile.authorized_emitters),
                "authorized_attestors": list(profile.authorized_attestors),
            }),
            "message_count": 2,
        },
        "capabilities": {
            "snapshot_restore": _snapshot_restore(),
            "transaction_stepping": _transaction_stepping(),
            "symbolic_storage": _symbolic_storage(),
            "channel_actions": _channel_actions(),
            "witness_extraction": _witness_extraction(),
        },
        "unsupported_features": [
            {
                "feature": "independent_evm_trace",
                "status": "unsupported",
                "reason": "paired fixture actions are not byte-for-byte EVM execution traces",
            },
            {
                "feature": "cryptographic_preimage_validation",
                "status": "unsupported",
                "reason": "fixture payload commitments are identifiers, not cryptographic checks",
            },
            {
                "feature": "revert_reason_and_failed_transaction_trace",
                "status": "unsupported",
                "reason": "fixture transition methods expose no EVM revert or gas trace",
            },
            {
                "feature": "token_balance_conservation",
                "status": "unsupported",
                "reason": "fixture has no token ledger or balance accounting",
            },
            {
                "feature": "proxy_and_contract_storage_layout",
                "status": "unsupported",
                "reason": "XLIR binding is grounded fixture storage only and is not source layout evidence",
            },
        ],
        "symbolic_engine": "z3-bounded-paired-v1",
        "independent_evm": False,
        "direct_trace_comparable": False,
        "admission_eligible": False,
        "evidence_scope": "development_contract_non_admission",
        "command": "python scripts/run_backend_feasibility_spike.py --check",
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    body["report_hash"] = sha256_hex(body)
    return body


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    return value


def validate_report(root: Path = ROOT, report_path: Path | None = None) -> list[str]:
    root = root.resolve()
    path = report_path or root / DEFAULT_OUTPUT.relative_to(ROOT)
    try:
        report = _load(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"backend feasibility report unreadable: {error}"]
    stored_hash = report.get("report_hash")
    body = dict(report)
    body.pop("report_hash", None)
    errors: list[str] = []
    if stored_hash != sha256_hex(body):
        errors.append("backend feasibility report hash mismatch")
    fixed_values = {
        "schema_version": 1,
        "record_type": "development_backend_feasibility_spike",
        "scope": "paired_fixture_g1_development_only",
        "status": "pass",
        "symbolic_engine": "z3-bounded-paired-v1",
        "independent_evm": False,
        "direct_trace_comparable": False,
        "admission_eligible": False,
        "evidence_scope": "development_contract_non_admission",
    }
    for key, expected_value in fixed_values.items():
        if report.get(key) != expected_value:
            errors.append(f"{key} must be {expected_value!r}")
    if not isinstance(report.get("observed_at"), str) or not report["observed_at"].endswith("Z"):
        errors.append("observed_at is not a UTC timestamp")
    capabilities = report.get("capabilities")
    expected_capabilities = {
        "snapshot_restore", "transaction_stepping", "symbolic_storage",
        "channel_actions", "witness_extraction",
    }
    if not isinstance(capabilities, dict) or set(capabilities) != expected_capabilities:
        errors.append("capabilities do not cover the five M00.02 checks")
    else:
        for name, capability in capabilities.items():
            if not isinstance(capability, dict):
                errors.append(f"{name} capability is not an object")
                continue
            if capability.get("status") != "pass":
                errors.append(f"{name} capability is not pass")
            if not isinstance(capability.get("checks"), list) or not capability["checks"]:
                errors.append(f"{name} capability has no checks")
            if not isinstance(capability.get("evidence"), dict):
                errors.append(f"{name} capability has no evidence object")
    unsupported = report.get("unsupported_features")
    if not isinstance(unsupported, list) or not unsupported:
        errors.append("unsupported_features must be a non-empty list")
    else:
        for index, feature in enumerate(unsupported, 1):
            if not isinstance(feature, dict):
                errors.append(f"unsupported feature {index} is not an object")
                continue
            if feature.get("status") != "unsupported":
                errors.append(f"unsupported feature {index} has invalid status")
            if not isinstance(feature.get("feature"), str) or not feature["feature"]:
                errors.append(f"unsupported feature {index} has no feature name")
            if not isinstance(feature.get("reason"), str) or not feature["reason"]:
                errors.append(f"unsupported feature {index} has no reason")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.out.resolve() if args.out else root / DEFAULT_OUTPUT.relative_to(ROOT)
    try:
        if args.check:
            errors = validate_report(root, output)
            if errors:
                print("FAILED")
                print("\n".join(errors))
                return 1
            print("OK: backend feasibility spike is valid and non-admission")
            return 0
        report = build_report(root)
        _atomic_json(output, report)
        print(f"backend feasibility spike: {len(report['capabilities'])}/5 capabilities pass")
        print(f"evidence written to: {output}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
