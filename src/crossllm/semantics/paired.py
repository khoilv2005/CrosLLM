"""A deterministic paired-chain fixture for transition and replay tests.

This is deliberately not an EVM implementation. It provides the state/channel
contract that a concrete EVM adapter must satisfy later.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Action(StrEnum):
    ENQUEUE = "enqueue"
    DELIVER = "deliver"


@dataclass(frozen=True, slots=True)
class Message:
    source_domain: str
    destination_domain: str
    emitter: str
    recipient: str
    nonce: int
    payload_commitment: str

    def identity(self) -> tuple[str, str, str, str, int, str]:
        return (
            self.source_domain,
            self.destination_domain,
            self.emitter,
            self.recipient,
            self.nonce,
            self.payload_commitment,
        )


@dataclass(slots=True)
class ChainState:
    domain: str
    storage: dict[str, Any] = field(default_factory=dict)
    committed_messages: list[Message] = field(default_factory=list)


@dataclass(slots=True)
class DualChainState:
    source: ChainState
    destination: ChainState
    pending: list[Message] = field(default_factory=list)
    delivered: list[Message] = field(default_factory=list)
    clocks: dict[str, int] = field(default_factory=dict)


class PairedFixture:
    """Bounded message fixture with isolated snapshot/restore semantics."""

    def __init__(self, source_domain: str = "source", destination_domain: str = "destination") -> None:
        if source_domain == destination_domain:
            raise ValueError("source and destination domains must differ")
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
        if any(existing.identity() == message.identity() for existing in self.state.pending):
            raise ValueError("duplicate pending message identity")
        self.state.pending.append(message)
        self.state.source.committed_messages.append(message)
        self.state.clocks[message.source_domain] += 1

    def deliver(self, index: int = 0) -> Message:
        if not self.state.pending:
            raise ValueError("cannot deliver from an empty channel")
        if index < 0 or index >= len(self.state.pending):
            raise IndexError("pending message index out of bounds")
        message = self.state.pending.pop(index)
        self.state.delivered.append(message)
        self.state.destination.storage[f"received:{message.nonce}"] = message.payload_commitment
        self.state.clocks[message.destination_domain] += 1
        return message

    def _validate_message(self, message: Message) -> None:
        if message.source_domain != self.state.source.domain:
            raise ValueError("message source domain mismatch")
        if message.destination_domain != self.state.destination.domain:
            raise ValueError("message destination domain mismatch")
        if message.nonce < 0:
            raise ValueError("message nonce must be non-negative")
        if not message.emitter or not message.recipient or not message.payload_commitment:
            raise ValueError("message identity fields must be non-empty")
