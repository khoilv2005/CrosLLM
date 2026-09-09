"""Native replay checker for the deterministic fixture.

This is deliberately not the independent EVM replay required by M05.03. Its
role is to validate witness decoding and the native transition contract before
the real EVM adapter exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts.canonical import sha256_hex
from ..contracts.records import ReplayStatus
from ..semantics import PairedFixture
from .witness import Witness, action_from_dict, replay_action_records, state_hash


@dataclass(frozen=True, slots=True)
class ReplayResult:
    status: ReplayStatus
    executed_actions: int
    initial_state_match: bool
    trace_hash_match: bool
    reason: str | None = None


class NativeReplay:
    """Check a witness against the same in-memory fixture used for search."""

    def check(self, witness: Witness | dict[str, object], initial_fixture: PairedFixture) -> ReplayResult:
        try:
            data = witness.as_dict() if isinstance(witness, Witness) else witness
            if not isinstance(data, dict):
                raise ValueError("witness must be an object")
            initial_match = data.get("initial_state_hash") == state_hash(initial_fixture.state)
            if not initial_match:
                return ReplayResult(ReplayStatus.FAIL, 0, False, False, "initial_state_hash_mismatch")
            rows = data.get("actions")
            if not isinstance(rows, list):
                raise ValueError("witness actions must be an array")
            actions = tuple(action_from_dict(row) for row in rows)
            normalized = [
                {
                    "action": action.action.value,
                    "message": _message_dict(action.message),
                    "transaction_index": action.transaction_index,
                    "channel_transition_index": action.channel_transition_index,
                    "pending_before": action.pending_before,
                    "pending_after": action.pending_after,
                }
                for action in actions
            ]
            trace_match = data.get("trace_hash") == sha256_hex(normalized)
            if not trace_match:
                return ReplayResult(ReplayStatus.FAIL, 0, True, False, "trace_hash_mismatch")
            replay_action_records(initial_fixture, actions)
            return ReplayResult(ReplayStatus.PASS, len(actions), True, True)
        except (ValueError, KeyError, TypeError) as error:
            return ReplayResult(ReplayStatus.FAIL, 0, False, False, f"invalid_witness:{error}")


def _message_dict(message: object) -> dict[str, object]:
    return {
        "source_domain": message.source_domain,  # type: ignore[attr-defined]
        "destination_domain": message.destination_domain,  # type: ignore[attr-defined]
        "emitter": message.emitter,  # type: ignore[attr-defined]
        "recipient": message.recipient,  # type: ignore[attr-defined]
        "nonce": message.nonce,  # type: ignore[attr-defined]
        "intent_id": message.intent_id,  # type: ignore[attr-defined]
        "payload_commitment": message.payload_commitment,  # type: ignore[attr-defined]
        "attestation": message.attestation,  # type: ignore[attr-defined]
        "attestor": message.attestor,  # type: ignore[attr-defined]
    }
