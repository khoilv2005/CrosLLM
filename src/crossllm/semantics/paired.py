"""A deterministic paired-chain fixture for transition and replay tests.

This is deliberately not an EVM implementation. It provides the state/channel
contract that a concrete EVM adapter must satisfy later.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..contracts.canonical import sha256_hex


class Action(StrEnum):
    ENQUEUE = "enqueue"
    DELIVER = "deliver"
    REORG = "reorg"


@dataclass(frozen=True, slots=True)
class TransitionBounds:
    """Finite bounds shared by concrete fixtures and later symbolic backends.

    ``max_transactions`` counts externally visible source/destination actions.
    ``max_channel_transitions`` counts enqueue and delivery separately.  Internal
    effects within an action deliberately do not consume another transaction.
    """

    max_transactions: int = 6
    max_channel_transitions: int = 12
    max_pending: int = 2

    def __post_init__(self) -> None:
        for name, value in (
            ("max_transactions", self.max_transactions),
            ("max_channel_transitions", self.max_channel_transitions),
            ("max_pending", self.max_pending),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class TransitionProfile:
    """Explicit channel/adversary policy for a fixture.

    Attestation fields are identifiers checked against this fixed profile. They
    are not cryptographic signatures, key ownership, or consensus evidence.
    """

    allow_reordering: bool = True
    allow_duplicate_enqueue: bool = False
    allow_pre_finality_reorg: bool = False
    finality_depth: int = 0
    require_attestation: bool = False
    authorized_emitters: tuple[str, ...] = ()
    authorized_attestors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.finality_depth < 0:
            raise ValueError("finality_depth must be non-negative")
        if self.allow_pre_finality_reorg and self.finality_depth < 1:
            raise ValueError("pre-finality reorg requires finality_depth >= 1")
        for name, values in (
            ("authorized_emitters", self.authorized_emitters),
            ("authorized_attestors", self.authorized_attestors),
        ):
            if any(not value for value in values):
                raise ValueError(f"{name} cannot contain empty identifiers")


@dataclass(frozen=True, slots=True)
class Message:
    source_domain: str
    destination_domain: str
    emitter: str
    recipient: str
    nonce: int
    payload_commitment: str
    attestation: str | None = None
    attestor: str | None = None
    intent_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "source_domain", "destination_domain", "emitter", "recipient",
            "payload_commitment",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        if (
            not isinstance(self.nonce, int)
            or isinstance(self.nonce, bool)
            or not 0 <= self.nonce < 2**256
        ):
            raise ValueError("nonce must be a uint256")
        for name in ("attestation", "attestor", "intent_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{name} must be a non-empty string when present")

    def identity(self) -> tuple[str, str, str, str, int, str, str]:
        return (
            self.source_domain,
            self.destination_domain,
            self.emitter,
            self.recipient,
            self.nonce,
            self.intent_id or "",
            self.payload_commitment,
        )


@dataclass(slots=True)
class ChainState:
    domain: str
    storage: dict[str, Any] = field(default_factory=dict)
    committed_messages: list[Message] = field(default_factory=list)
    canonical_history: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ActionRecord:
    """Immutable action evidence, separate from the mutable contract state."""

    action: Action
    message: Message
    transaction_index: int
    channel_transition_index: int
    pending_before: int
    pending_after: int


@dataclass(slots=True)
class DualChainState:
    source: ChainState
    destination: ChainState
    pending: list[Message] = field(default_factory=list)
    delivered: list[Message] = field(default_factory=list)
    clocks: dict[str, int] = field(default_factory=dict)
    observer_state: dict[str, Any] = field(default_factory=dict)
    transaction_count: int = 0
    channel_transition_count: int = 0
    action_log: list[ActionRecord] = field(default_factory=list)


class PairedFixture:
    """Bounded message fixture with isolated snapshot/restore semantics."""

    def __init__(
        self,
        source_domain: str = "source",
        destination_domain: str = "destination",
        *,
        bounds: TransitionBounds | None = None,
        profile: TransitionProfile | None = None,
    ) -> None:
        if source_domain == destination_domain:
            raise ValueError("source and destination domains must differ")
        self.bounds = bounds or TransitionBounds()
        self.profile = profile or TransitionProfile()
        self._initial = DualChainState(
            source=ChainState(source_domain),
            destination=ChainState(destination_domain),
            clocks={source_domain: 0, destination_domain: 0},
        )
        self.state = deepcopy(self._initial)

    def snapshot(self) -> DualChainState:
        return deepcopy(self.state)

    def restore(self, snapshot: DualChainState) -> None:
        if snapshot.source.domain != self.state.source.domain:
            raise ValueError("snapshot source domain mismatch")
        if snapshot.destination.domain != self.state.destination.domain:
            raise ValueError("snapshot destination domain mismatch")
        self.state = deepcopy(snapshot)

    def reset(self) -> None:
        self.state = deepcopy(self._initial)

    def enqueue(self, message: Message) -> None:
        self._validate_message(message)
        self._require_capacity(Action.ENQUEUE)
        if len(self.state.pending) >= self.bounds.max_pending:
            raise ValueError("pending channel bound exhausted")
        if (
            not self.profile.allow_duplicate_enqueue
            and any(existing.identity() == message.identity() for existing in self.state.source.committed_messages)
        ):
            raise ValueError("duplicate message identity")
        pending_before = len(self.state.pending)
        self.state.pending.append(message)
        self.state.source.committed_messages.append(message)
        self.state.source.canonical_history.append(self._message_key(message))
        self.state.clocks[message.source_domain] += 1
        self._record_action(Action.ENQUEUE, message, pending_before)

    def deliver(self, index: int = 0) -> Message:
        if not self.state.pending:
            raise ValueError("cannot deliver from an empty channel")
        if index < 0 or index >= len(self.state.pending):
            raise IndexError("pending message index out of bounds")
        if not self.profile.allow_reordering and index != 0:
            raise ValueError("reordering is disabled by transition profile")
        self._require_capacity(Action.DELIVER)
        pending_before = len(self.state.pending)
        message = self.state.pending.pop(index)
        self.state.delivered.append(message)
        self.state.destination.canonical_history.append(self._message_key(message))
        self.state.destination.storage[f"received:{message.nonce}"] = message.payload_commitment
        self.state.clocks[message.destination_domain] += 1
        self._record_action(Action.DELIVER, message, pending_before)
        return message

    def reorg_latest(self) -> Message:
        """Rollback the latest pending source message before finality."""
        return self.reorg()

    def reorg(self, index: int = -1) -> Message:
        """Rollback one pending source message if it is not finalized.

        The number of later committed source messages is the fixture's
        confirmation count.  This makes ``finality_depth`` operational instead
        of merely documenting a profile: a message with confirmations greater
        than or equal to the depth cannot be removed by the adversary.
        """
        if not self.profile.allow_pre_finality_reorg:
            raise ValueError("pre-finality reorg is disabled by transition profile")
        if not self.state.source.committed_messages:
            raise ValueError("cannot reorg an empty canonical history")
        if index < 0:
            index += len(self.state.source.committed_messages)
        if index < 0 or index >= len(self.state.source.committed_messages):
            raise IndexError("committed message index out of bounds")
        confirmations = len(self.state.source.committed_messages) - 1 - index
        if confirmations >= self.profile.finality_depth:
            raise ValueError("message is finalized by transition profile")
        self._require_capacity(Action.REORG, channel_transition=False)
        message = self.state.source.committed_messages[index]
        key = message.identity()
        if not any(existing.identity() == key for existing in self.state.pending):
            raise ValueError("cannot reorg a message already delivered")
        pending_before = len(self.state.pending)
        pending_index = next(
            (index for index in range(len(self.state.pending) - 1, -1, -1)
             if self.state.pending[index].identity() == key),
            None,
        )
        if pending_index is None:
            raise ValueError("cannot reorg a message already delivered")
        del self.state.pending[pending_index]
        del self.state.source.committed_messages[index]
        del self.state.source.canonical_history[index]
        self.state.clocks[message.source_domain] -= 1
        self._record_action(Action.REORG, message, pending_before, channel_transition=False)
        return message

    def observe(self, key: str, value: Any) -> None:
        """Store ghost-observer data without mutating either chain's storage."""
        if not key:
            raise ValueError("observer key must be non-empty")
        self.state.observer_state[key] = deepcopy(value)

    def _require_capacity(self, action: Action, *, channel_transition: bool = True) -> None:
        if self.state.transaction_count >= self.bounds.max_transactions:
            raise ValueError(f"transaction bound exhausted before {action.value}")
        if channel_transition and self.state.channel_transition_count >= self.bounds.max_channel_transitions:
            raise ValueError(f"channel transition bound exhausted before {action.value}")

    def _record_action(
        self,
        action: Action,
        message: Message,
        pending_before: int,
        *,
        channel_transition: bool = True,
    ) -> None:
        self.state.transaction_count += 1
        if channel_transition:
            self.state.channel_transition_count += 1
        self.state.action_log.append(
            ActionRecord(
                action=action,
                message=message,
                transaction_index=self.state.transaction_count,
                channel_transition_index=self.state.channel_transition_count,
                pending_before=pending_before,
                pending_after=len(self.state.pending),
            )
        )

    @staticmethod
    def _message_key(message: Message) -> str:
        return sha256_hex(message.identity())

    def _validate_message(self, message: Message) -> None:
        if message.source_domain != self.state.source.domain:
            raise ValueError("message source domain mismatch")
        if message.destination_domain != self.state.destination.domain:
            raise ValueError("message destination domain mismatch")
        if not isinstance(message.nonce, int) or isinstance(message.nonce, bool) or not 0 <= message.nonce < 2**256:
            raise ValueError("message nonce must be a uint256")
        if not message.emitter or not message.recipient or not message.payload_commitment:
            raise ValueError("message identity fields must be non-empty")
        if message.intent_id is not None and (
            not isinstance(message.intent_id, str) or not message.intent_id
        ):
            raise ValueError("intent_id must be a non-empty string when present")
        if self.profile.authorized_emitters and message.emitter not in self.profile.authorized_emitters:
            raise ValueError("message emitter is not authorized by transition profile")
        if self.profile.require_attestation:
            if not message.attestation or not message.attestor:
                raise ValueError("message requires an attestation and attestor")
            if message.attestor not in self.profile.authorized_attestors:
                raise ValueError("message attestor is not authorized by transition profile")
        elif message.attestation is not None and not message.attestation:
            raise ValueError("attestation cannot be empty")
