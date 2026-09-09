"""Project bounded fixture evidence into the versioned witness contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from ..backends import SearchResult, SymbolicSearchResult
from ..contracts.canonical import sha256_hex
from ..contracts.records import SearchStatus
from ..semantics import Action, ActionRecord, DualChainState, Message, PairedFixture


class WitnessProjectionError(ValueError):
    """A search result cannot be represented as an executable witness."""


@dataclass(frozen=True, slots=True)
class Witness:
    schema_version: int
    witness_id: str
    query_id: str
    initial_state_hash: str
    trace_hash: str
    actions: tuple[dict[str, object], ...]
    domains: tuple[str, ...]
    created_at: str
    proof_objects: dict[str, object]
    native_replay_status: str = "unknown"
    independent_replay_status: str = "unknown"
    security_relevance: str = "unassessed"
    allowed_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported witness schema_version")
        for name in ("witness_id", "query_id", "created_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        for name in ("initial_state_hash", "trace_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
        if not isinstance(self.actions, tuple):
            raise ValueError("witness actions must be a tuple")
        if not isinstance(self.domains, tuple) or any(
            not isinstance(domain, str) or not domain for domain in self.domains
        ) or len(set(self.domains)) != len(self.domains):
            raise ValueError("witness domains must be unique non-empty strings")
        if not isinstance(self.proof_objects, dict):
            raise ValueError("witness proof_objects must be an object")
        if self.native_replay_status not in {"pass", "fail", "unknown", "unsupported"}:
            raise ValueError("invalid native_replay_status")
        if self.independent_replay_status not in {"pass", "fail", "unknown", "unsupported"}:
            raise ValueError("invalid independent_replay_status")
        if self.security_relevance not in {"unassessed", "relevant", "irrelevant", "unknown"}:
            raise ValueError("invalid security_relevance")
        if not isinstance(self.allowed_capabilities, tuple) or any(
            not isinstance(capability, str) or not capability
            for capability in self.allowed_capabilities
        ) or len(set(self.allowed_capabilities)) != len(self.allowed_capabilities):
            raise ValueError("allowed_capabilities must be unique non-empty strings")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "witness_id": self.witness_id,
            "query_id": self.query_id,
            "initial_state_hash": self.initial_state_hash,
            "trace_hash": self.trace_hash,
            "actions": list(self.actions),
            "domains": list(self.domains),
            "created_at": self.created_at,
            "proof_objects": self.proof_objects,
            "native_replay_status": self.native_replay_status,
            "independent_replay_status": self.independent_replay_status,
            "security_relevance": self.security_relevance,
            "allowed_capabilities": list(self.allowed_capabilities),
        }


class WitnessProjector:
    """Turn only a SAT result into a concrete, replayable native witness."""

    def project(
        self,
        result: SearchResult | SymbolicSearchResult,
        initial_fixture: PairedFixture,
        *,
        witness_id: str,
        query_id: str,
        created_at: str | None = None,
        proof_objects: dict[str, object] | None = None,
        allowed_capabilities: tuple[str, ...] = (),
    ) -> Witness:
        if result.status is not SearchStatus.SAT or not result.complete:
            raise WitnessProjectionError("only complete SAT results can produce a witness")
        if not witness_id or not query_id:
            raise WitnessProjectionError("witness_id and query_id are required")
        action_rows = tuple(_action_to_dict(action) for action in result.witness)
        try:
            replay_action_records(initial_fixture, result.witness)
        except ValueError as error:
            raise WitnessProjectionError(f"search witness is not replayable: {error}") from error
        domains = tuple(sorted({domain for action in result.witness for domain in _action_domains(action)}))
        return Witness(
            schema_version=1,
            witness_id=witness_id,
            query_id=query_id,
            initial_state_hash=state_hash(initial_fixture.state),
            trace_hash=sha256_hex(list(action_rows)),
            actions=action_rows,
            domains=domains,
            created_at=created_at or datetime.now(timezone.utc).isoformat(),
            proof_objects=dict(proof_objects or {}),
            allowed_capabilities=tuple(allowed_capabilities),
        )


def replay_action_records(initial_fixture: PairedFixture, actions: tuple[ActionRecord, ...] | list[ActionRecord]) -> PairedFixture:
    """Apply action records to a cloned fixture and reject any mismatch."""
    fixture = _clone_fixture(initial_fixture)
    for expected in actions:
        try:
            action = Action(expected.action)
        except ValueError as error:
            raise ValueError(f"unsupported action {expected.action!r}") from error
        if action is Action.ENQUEUE:
            fixture.enqueue(expected.message)
        elif action is Action.DELIVER:
            fixture.deliver(_pending_index(fixture, expected.message))
        elif action is Action.REORG:
            fixture.reorg_latest()
        else:
            raise ValueError(f"unsupported action {action.value}")
        actual = fixture.state.action_log[-1]
        if actual.action is not action or actual.message.identity() != expected.message.identity():
            raise ValueError("action evidence does not match replay result")
        if actual.transaction_index != expected.transaction_index:
            raise ValueError("transaction index mismatch")
        if actual.channel_transition_index != expected.channel_transition_index:
            raise ValueError("channel transition index mismatch")
    return fixture


def action_from_dict(row: object) -> ActionRecord:
    """Decode one untrusted witness action with strict required fields."""
    if not isinstance(row, dict):
        raise ValueError("witness action must be an object")
    allowed = {
        "action", "message", "transaction_index", "channel_transition_index",
        "pending_before", "pending_after",
    }
    extras = set(row) - allowed
    if extras:
        raise ValueError(f"witness action has unsupported fields: {', '.join(sorted(extras))}")
    try:
        action = Action(row.get("action"))
    except ValueError as error:
        raise ValueError("witness action has invalid action") from error
    raw_message = row.get("message")
    if not isinstance(raw_message, dict):
        raise ValueError("witness action message must be an object")
    required = ("source_domain", "destination_domain", "emitter", "recipient", "nonce", "payload_commitment")
    if any(field not in raw_message for field in required):
        raise ValueError("witness action message is missing required fields")
    message_allowed = set(required) | {"intent_id", "attestation", "attestor"}
    message_extras = set(raw_message) - message_allowed
    if message_extras:
        raise ValueError(
            "witness action message has unsupported fields: "
            + ", ".join(sorted(message_extras))
        )
    for field in ("source_domain", "destination_domain", "emitter", "recipient", "payload_commitment"):
        value = raw_message[field]
        if not isinstance(value, str) or not value:
            raise ValueError(f"witness action message {field} must be a non-empty string")
    nonce = raw_message["nonce"]
    if not isinstance(nonce, int) or isinstance(nonce, bool) or not 0 <= nonce < 2**256:
        raise ValueError("witness action message nonce must be a uint256")
    intent_id = raw_message.get("intent_id")
    for field in ("intent_id", "attestation", "attestor"):
        value = raw_message.get(field)
        if value is not None and (not isinstance(value, str) or not value):
            raise ValueError(f"witness action {field} must be a non-empty string when present")
    message = Message(
        raw_message["source_domain"],
        raw_message["destination_domain"],
        raw_message["emitter"],
        raw_message["recipient"],
        nonce,
        raw_message["payload_commitment"],
        raw_message.get("attestation"),
        raw_message.get("attestor"),
        intent_id,
    )
    indices = ("transaction_index", "channel_transition_index", "pending_before", "pending_after")
    if any(
        not isinstance(row.get(field), int)
        or isinstance(row.get(field), bool)
        or row[field] < 0
        for field in indices
    ):
        raise ValueError("witness action indices must be integers")
    return ActionRecord(action, message, *(row[field] for field in indices))


def state_hash(state: DualChainState) -> str:
    """Hash all fixture state relevant to replay and observer separation."""
    return sha256_hex(
        {
            "source": _chain_dict(state.source),
            "destination": _chain_dict(state.destination),
            "pending": [_message_dict(message) for message in state.pending],
            "delivered": [_message_dict(message) for message in state.delivered],
            "clocks": state.clocks,
            "observer_state": state.observer_state,
            "transaction_count": state.transaction_count,
            "channel_transition_count": state.channel_transition_count,
            "action_log": [_action_to_dict(action) for action in state.action_log],
        }
    )


def _clone_fixture(fixture: PairedFixture) -> PairedFixture:
    clone = PairedFixture(
        fixture.state.source.domain,
        fixture.state.destination.domain,
        bounds=fixture.bounds,
        profile=fixture.profile,
    )
    clone.restore(fixture.snapshot())
    return clone


def _pending_index(fixture: PairedFixture, message: Message) -> int:
    for index, pending in enumerate(fixture.state.pending):
        if pending.identity() == message.identity():
            return index
    raise ValueError("delivery message is not pending")


def _action_domains(action: ActionRecord) -> tuple[str, ...]:
    return (action.message.source_domain, action.message.destination_domain)


def _message_dict(message: Message) -> dict[str, object]:
    return {
        "source_domain": message.source_domain,
        "destination_domain": message.destination_domain,
        "emitter": message.emitter,
        "recipient": message.recipient,
        "nonce": message.nonce,
        "intent_id": message.intent_id,
        "payload_commitment": message.payload_commitment,
        "attestation": message.attestation,
        "attestor": message.attestor,
    }


def _action_to_dict(action: ActionRecord) -> dict[str, object]:
    return {
        "action": action.action.value,
        "message": _message_dict(action.message),
        "transaction_index": action.transaction_index,
        "channel_transition_index": action.channel_transition_index,
        "pending_before": action.pending_before,
        "pending_after": action.pending_after,
    }


def _chain_dict(chain: object) -> dict[str, object]:
    return {
        "domain": chain.domain,  # type: ignore[attr-defined]
        "storage": chain.storage,  # type: ignore[attr-defined]
        "committed_messages": [
            _message_dict(message) for message in chain.committed_messages  # type: ignore[attr-defined]
        ],
        "canonical_history": list(chain.canonical_history),  # type: ignore[attr-defined]
    }
