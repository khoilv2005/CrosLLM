"""Deliberate replay negative controls for the development boundary (M05.05)."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Any

from ..artifacts import ArtifactSymbol
from ..backends import BoundedPairedExplorer
from ..contracts.canonical import sha256_hex
from ..contracts.records import ReplayStatus
from ..semantics import Message, PairedFixture, TransitionBounds, TransitionProfile
from ..xlir import XLIRCompiler, evaluate_invariant
from .native import NativeReplay
from .witness import WitnessProjector


CASE_IDS = (
    "wrong_property",
    "altered_witness",
    "infeasible_signature",
    "wrong_initial_state",
    "callback_ordering",
    "patched_control",
)


@dataclass(frozen=True, slots=True)
class NegativeControlResult:
    case_id: str
    control_kind: str
    expected_outcome: str
    observed_status: str
    observed_reason: str
    passed: bool
    evidence_hash: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "control_kind": self.control_kind,
            "expected_outcome": self.expected_outcome,
            "observed_status": self.observed_status,
            "observed_reason": self.observed_reason,
            "passed": self.passed,
            "evidence_hash": self.evidence_hash,
        }


def run_negative_controls(source_mutation_report: Path) -> tuple[NegativeControlResult, ...]:
    """Run all six deliberate controls without exposing witness contents."""
    fixture, witness = _fixture_witness()
    replay = NativeReplay()
    results = [
        _wrong_property_control(),
        _replay_failure(
            replay,
            fixture,
            replace(witness, trace_hash="0" * 64),
            "altered_witness",
            "altered witness must be rejected",
            "trace_hash_mismatch",
        ),
        _infeasible_signature_control(replay, fixture, witness),
        _replay_failure(
            replay,
            fixture,
            replace(witness, initial_state_hash="0" * 64),
            "wrong_initial_state",
            "wrong initial state must be rejected",
            "initial_state_hash_mismatch",
        ),
        _callback_ordering_control(),
        _patched_control(source_mutation_report),
    ]
    if tuple(result.case_id for result in results) != CASE_IDS:
        raise AssertionError("negative-control coverage order is not canonical")
    return tuple(results)


def _fixture_witness() -> tuple[PairedFixture, Any]:
    def message(nonce: int) -> Message:
        return Message("source", "destination", "bridge", "receiver", nonce, f"commit-{nonce}")

    fixture = PairedFixture(bounds=TransitionBounds(4, 4, 2))
    result = BoundedPairedExplorer([message(1), message(2)]).search(
        fixture,
        lambda state: bool(state.delivered)
        and state.delivered[0].nonce == 2
        and any(pending.nonce == 1 for pending in state.pending),
    )
    if not result.complete:
        raise RuntimeError("negative-control fixture search was incomplete")
    witness = WitnessProjector().project(
        result, fixture, witness_id="negative-control-witness", query_id="negative-control-query"
    )
    return fixture, witness


def _wrong_property_control() -> NegativeControlResult:
    symbols = [ArtifactSymbol("sym.destination.executed", "Bridge.sol", "executed", "destination", "storage", "bool")]
    result = XLIRCompiler.from_symbols(symbols).compile({
        "kind": "invariant",
        "body": {
            "kind": "binary", "operator": "eq",
            "left": {"kind": "symbol", "symbol_id": "sym.destination.executed", "state": "post"},
            "right": {"kind": "literal", "type": "bool", "value": True},
        },
    })
    if not result.ok or result.invariant is None:
        return NegativeControlResult(
            "wrong_property", "property_evaluator", "not_satisfied", "compile_failure",
            "wrong property failed to compile", False,
        )
    satisfied = evaluate_invariant(
        result.invariant,
        {("sym.destination.executed", "post", "destination"): False},
    )
    return NegativeControlResult(
        "wrong_property", "property_evaluator", "not_satisfied",
        "not_satisfied" if not satisfied else "satisfied",
        "deliberately wrong property evaluates false on the replay post-state",
        not satisfied,
    )


def _replay_failure(
    replay: NativeReplay,
    fixture: PairedFixture,
    witness: Any,
    case_id: str,
    expected_outcome: str,
    expected_reason: str,
) -> NegativeControlResult:
    result = replay.check(witness, fixture)
    reason = result.reason or ""
    return NegativeControlResult(
        case_id,
        "native_replay",
        expected_outcome,
        "rejected" if result.status is ReplayStatus.FAIL else result.status.value,
        reason,
        result.status is ReplayStatus.FAIL and reason == expected_reason,
    )


def _infeasible_signature_control(replay: NativeReplay, fixture: PairedFixture, witness: Any) -> NegativeControlResult:
    rows = [dict(row) for row in witness.as_dict()["actions"]]
    delivery = dict(rows[-1])
    message = dict(delivery["message"])
    message["nonce"] = 2**256 - 1
    delivery["message"] = message
    rows[-1] = delivery
    tampered = dict(witness.as_dict(), actions=rows, trace_hash=sha256_hex(rows))
    result = replay.check(tampered, fixture)
    reason = result.reason or ""
    return NegativeControlResult(
        "infeasible_signature",
        "native_replay",
        "rejected",
        "rejected" if result.status is ReplayStatus.FAIL else result.status.value,
        reason,
        result.status is ReplayStatus.FAIL and reason.startswith("invalid_witness:"),
    )


def _callback_ordering_control() -> NegativeControlResult:
    fixture = PairedFixture(
        bounds=TransitionBounds(4, 4, 2),
        profile=TransitionProfile(allow_reordering=False),
    )
    first = Message("source", "destination", "bridge", "receiver", 1, "commit-1")
    second = Message("source", "destination", "bridge", "receiver", 2, "commit-2")
    fixture.enqueue(first)
    fixture.enqueue(second)
    try:
        fixture.deliver(index=1)
    except ValueError as error:
        reason = str(error)
        return NegativeControlResult(
            "callback_ordering", "transition_profile", "rejected", "rejected", reason,
            reason == "reordering is disabled by transition profile",
        )
    return NegativeControlResult(
        "callback_ordering", "transition_profile", "rejected", "accepted",
        "forbidden callback/order was accepted", False,
    )


def _patched_control(source_mutation_report: Path) -> NegativeControlResult:
    try:
        rows = [
            json.loads(line)
            for line in source_mutation_report.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as error:
        return NegativeControlResult(
            "patched_control", "source_backed_control", "control_pass", "unavailable", str(error), False,
        )
    row = next((item for item in rows if item.get("operator_id") == "OP_FINALITY_WINDOW_TRUNCATION"), None)
    if not isinstance(row, dict):
        return NegativeControlResult(
            "patched_control", "source_backed_control", "control_pass", "unavailable",
            "source-backed finality control row is missing", False,
        )
    verified = row.get("control_status") == "PASS" and row.get("control_pair_verified") is True
    return NegativeControlResult(
        "patched_control", "source_backed_control", "control_pass",
        "control_pass" if verified else "control_failed",
        "locked patched/control source path rejects the early refund trigger",
        verified,
        hashlib.sha256(source_mutation_report.read_bytes()).hexdigest(),
    )


def build_report(source_mutation_report: Path) -> dict[str, object]:
    results = run_negative_controls(source_mutation_report)
    rows = [result.as_dict() for result in results]
    payload: dict[str, object] = {
        "schema_version": 1,
        "record_type": "replay_negative_control_report",
        "scope": "development_replay_boundary_controls",
        "case_ids": list(CASE_IDS),
        "cases": rows,
        "case_count": len(rows),
        "passed_count": sum(bool(row["passed"]) for row in rows),
        "all_passed": all(bool(row["passed"]) for row in rows),
        "source_mutation_report_sha256": hashlib.sha256(source_mutation_report.read_bytes()).hexdigest(),
        # Keep the report portable; the absolute path is an execution detail,
        # not part of the evidence identity.
        "source_mutation_report": "dataset/reports/source_mutation_evidence.jsonl",
        "source_backed": True,
        "independent_property_validation": False,
        "independent_trigger_validation": False,
        "admission_eligible": False,
        "evidence_scope": "development_replay_boundary_controls",
    }
    payload["report_hash"] = sha256_hex(payload)
    return payload


__all__ = ["CASE_IDS", "NegativeControlResult", "build_report", "run_negative_controls"]
