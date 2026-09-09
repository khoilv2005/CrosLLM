"""Development-only correspondence between the paired model and source EVM.

The paired fixture and Celer harness do not expose the same execution trace:
the fixture models channel enqueue/delivery/reorg, while Celer's native test
models transfer-out/transfer-in/confirm/refund.  This module records that
boundary explicitly.  It is useful for a differential spike and negative
coverage, but it never upgrades a structural mapping into an independent EVM
property result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..contracts.canonical import sha256_hex
from ..contracts.records import SearchStatus
from ..semantics import Message, PairedFixture, TransitionBounds, TransitionProfile
from ..backends import SymbolicPairedExplorer


@dataclass(frozen=True, slots=True)
class DifferentialCase:
    case_id: str
    source_test: str
    source_steps: tuple[str, ...]
    symbolic_status: str
    symbolic_complete: bool
    symbolic_reason: str
    symbolic_encoding_hash: str | None
    symbolic_actions: tuple[str, ...]
    fixture_projection: dict[str, Any]
    direct_trace_comparable: bool
    projection_status: str
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "source_test": self.source_test,
            "source_steps": list(self.source_steps),
            "symbolic": {
                "status": self.symbolic_status,
                "complete": self.symbolic_complete,
                "reason": self.symbolic_reason,
                "encoding_hash": self.symbolic_encoding_hash,
                "actions": list(self.symbolic_actions),
            },
            "fixture_projection": self.fixture_projection,
            "direct_trace_comparable": self.direct_trace_comparable,
            "projection_status": self.projection_status,
            "note": self.note,
        }


def _message() -> Message:
    return Message(
        "DomainA",
        "DomainB",
        "userSender",
        "userReceiver",
        0,
        sha256_hex({"hashlock": "development-secret", "amount": "100"}),
        intent_id="celer-development-transfer-0",
    )


def _normal_case() -> DifferentialCase:
    message = _message()
    fixture = PairedFixture(
        source_domain="DomainA",
        destination_domain="DomainB",
        bounds=TransitionBounds(4, 4, 2),
    )
    result = SymbolicPairedExplorer([message]).search(
        fixture,
        lambda state: len(state.delivered) == 1 and not state.pending,
    )
    projected = PairedFixture(
        source_domain="DomainA",
        destination_domain="DomainB",
        bounds=TransitionBounds(4, 4, 2),
    )
    projected.enqueue(message)
    projected.deliver()
    return DifferentialCase(
        case_id="normal_confirm",
        source_test="test_normal_cross_chain_transfer_and_confirm",
        source_steps=("approve", "transferOut", "transferIn", "confirm"),
        symbolic_status=result.status.value,
        symbolic_complete=result.complete,
        symbolic_reason=result.reason or "",
        symbolic_encoding_hash=result.encoding_hash or None,
        symbolic_actions=tuple(item.action.value for item in result.witness),
        fixture_projection={
            "source_domain": projected.state.source.domain,
            "destination_domain": projected.state.destination.domain,
            "pending_after": len(projected.state.pending),
            "delivered_after": len(projected.state.delivered),
            "source_committed_after": len(projected.state.source.committed_messages),
            "destination_received_key": next(iter(projected.state.destination.storage)),
            "transaction_bound": fixture.bounds.max_transactions,
            "channel_bound": fixture.bounds.max_channel_transitions,
        },
        direct_trace_comparable=False,
        projection_status="structural_only",
        note="Fixture enqueue/deliver corresponds to the source workflow at the protocol-step level; token balances and hashlock execution are not represented by the fixture.",
    )


def _timeout_case() -> DifferentialCase:
    message = _message()
    fixture = PairedFixture(
        source_domain="DomainA",
        destination_domain="DomainB",
        bounds=TransitionBounds(3, 2, 1),
        profile=TransitionProfile(allow_pre_finality_reorg=True, finality_depth=1),
    )
    result = SymbolicPairedExplorer([message]).search(
        fixture,
        lambda state: not state.source.committed_messages and state.transaction_count == 2,
    )
    projected = PairedFixture(
        source_domain="DomainA",
        destination_domain="DomainB",
        bounds=TransitionBounds(3, 2, 1),
        profile=TransitionProfile(allow_pre_finality_reorg=True, finality_depth=1),
    )
    projected.enqueue(message)
    projected.reorg()
    return DifferentialCase(
        case_id="timeout_refund",
        source_test="test_transfer_timeout_and_refund",
        source_steps=("approve", "transferOut", "warp_after_timelock", "refund"),
        symbolic_status=result.status.value,
        symbolic_complete=result.complete,
        symbolic_reason=result.reason or "",
        symbolic_encoding_hash=result.encoding_hash or None,
        symbolic_actions=tuple(item.action.value for item in result.witness),
        fixture_projection={
            "source_domain": projected.state.source.domain,
            "destination_domain": projected.state.destination.domain,
            "pending_after": len(projected.state.pending),
            "source_committed_after": len(projected.state.source.committed_messages),
            "reorg_profile": "pre_finality_only",
            "finality_depth": fixture.profile.finality_depth,
        },
        direct_trace_comparable=False,
        projection_status="structural_only",
        note="Fixture reorg is the bounded channel analogue of removing an unfinalized transfer; timelock arithmetic and token refund are source-only behavior.",
    )


def _invalid_preimage_case() -> DifferentialCase:
    return DifferentialCase(
        case_id="invalid_preimage_revert",
        source_test="test_revert_confirm_incorrect_preimage",
        source_steps=("approve", "transferOut", "confirm_wrong_preimage"),
        symbolic_status=SearchStatus.UNSUPPORTED.value,
        symbolic_complete=False,
        symbolic_reason="fixture does not model cryptographic preimage validation or revert traces",
        symbolic_encoding_hash=None,
        symbolic_actions=(),
        fixture_projection={
            "unsupported": ["hashlock_validation", "revert_reason", "failed_transaction_trace"],
        },
        direct_trace_comparable=False,
        projection_status="unsupported",
        note="The source-backed negative test is retained as a boundary case; no fixture SAT/UNSAT claim is emitted.",
    )


def build_cases() -> tuple[DifferentialCase, ...]:
    return (_normal_case(), _timeout_case(), _invalid_preimage_case())


__all__ = ["DifferentialCase", "build_cases"]
