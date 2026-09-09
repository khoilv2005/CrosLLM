"""Exhaustive bounded exploration for the in-memory paired fixture.

This module is a test oracle for the transition contract.  It deliberately does
not lower Solidity or XLIR, and is kept separate from any future symbolic/EVM
backend so that agreement can be tested rather than assumed.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import time
from typing import Callable

from crossllm.contracts.canonical import sha256_hex
from crossllm.contracts.records import SearchStatus
from crossllm.semantics import ActionRecord, DualChainState, Message, PairedFixture


StatePredicate = Callable[[DualChainState], bool]
Clock = Callable[[], float]
Cancellation = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class SearchControl:
    """Runtime limits surrounding one bounded query."""

    query_timeout_seconds: float = 30.0
    campaign_deadline_seconds: float = 3600.0
    campaign_elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (
            self.query_timeout_seconds,
            self.campaign_deadline_seconds,
            self.campaign_elapsed_seconds,
        )):
            raise ValueError("search deadlines must be finite")
        if self.query_timeout_seconds <= 0 or self.campaign_deadline_seconds <= 0:
            raise ValueError("search deadlines must be positive")
        if self.query_timeout_seconds > self.campaign_deadline_seconds:
            raise ValueError("query timeout cannot exceed campaign deadline")
        if self.campaign_elapsed_seconds < 0:
            raise ValueError("campaign elapsed time cannot be negative")

    def remaining_seconds(self) -> float:
        """Return this query's remaining share of the campaign budget."""

        return min(
            self.query_timeout_seconds,
            max(0.0, self.campaign_deadline_seconds - self.campaign_elapsed_seconds),
        )

    def expiration_reason(self, elapsed_seconds: float) -> str:
        if self.campaign_elapsed_seconds + elapsed_seconds >= self.campaign_deadline_seconds:
            return "campaign_deadline"
        return "query_timeout"


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Result of a finite search; SAT evidence is an action sequence."""

    status: SearchStatus
    explored_states: int
    explored_paths: int
    schedule_count: int
    complete: bool
    reason: str | None = None
    witness: tuple[ActionRecord, ...] = ()
    elapsed_seconds: float = 0.0
    cache_hits: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "explored_states": self.explored_states,
            "explored_paths": self.explored_paths,
            "schedule_count": self.schedule_count,
            "complete": self.complete,
            "reason": self.reason,
            "elapsed_seconds": self.elapsed_seconds,
            "cache_hits": self.cache_hits,
            "witness_length": len(self.witness),
        }


class BoundedPairedExplorer:
    """Enumerate valid enqueue/deliver/reorg schedules under fixture bounds.

    The predicate must be a pure state predicate. Search fingerprints include
    contract state, observer state, clocks, full channel state, action history,
    and remaining bounds, so pruning cannot discard a distinct represented state.
    ``max_states`` is an operational guard: reaching it returns ``UNKNOWN``,
    never ``BOUNDED_UNSAT``.
    """

    def __init__(self, messages: tuple[Message, ...] | list[Message], *, max_states: int = 10_000) -> None:
        if max_states <= 0:
            raise ValueError("max_states must be positive")
        self.messages = tuple(messages)
        if len({message.identity() for message in self.messages}) != len(self.messages):
            raise ValueError("candidate messages must have unique identities")
        self.max_states = max_states

    def search(
        self,
        fixture: PairedFixture,
        violation: StatePredicate,
        *,
        control: SearchControl | None = None,
        clock: Clock = time.monotonic,
        cancelled: Cancellation | None = None,
    ) -> SearchResult:
        control = control or SearchControl()
        started = clock()
        queue: deque[PairedFixture] = deque([self._clone(fixture)])
        seen: set[str] = set()
        explored_paths = 0
        schedule_count = 0
        cache_hits = 0

        def result(status: SearchStatus, complete: bool, reason: str | None = None, witness: tuple[ActionRecord, ...] = ()) -> SearchResult:
            return SearchResult(
                status=status,
                explored_states=len(seen),
                explored_paths=explored_paths,
                schedule_count=schedule_count,
                complete=complete,
                reason=reason,
                witness=witness,
                elapsed_seconds=max(0.0, clock() - started),
                cache_hits=cache_hits,
            )

        while queue:
            elapsed = clock() - started
            if cancelled is not None and cancelled():
                return result(SearchStatus.UNKNOWN, False, "cancelled")
            query_budget = control.remaining_seconds()
            if query_budget <= 0:
                return result(SearchStatus.TIMEOUT, False, "campaign_deadline")
            if elapsed >= query_budget:
                return result(SearchStatus.TIMEOUT, False, control.expiration_reason(elapsed))
            if len(seen) >= self.max_states:
                return result(SearchStatus.UNKNOWN, False, "state_limit_exhausted")
            current = queue.popleft()
            fingerprint = self._fingerprint(current)
            if fingerprint in seen:
                cache_hits += 1
                continue
            seen.add(fingerprint)
            try:
                is_violation = bool(violation(current.state))
            except Exception as error:
                return result(
                    SearchStatus.CRASH,
                    False,
                    f"predicate_error:{type(error).__name__}:{error}",
                )
            if is_violation:
                return result(SearchStatus.SAT, True, witness=tuple(current.state.action_log))

            successors = self._successors(current)
            schedule_count += len(successors)
            explored_paths += len(successors)
            queue.extend(successors)

        return result(SearchStatus.BOUNDED_UNSAT, True, "finite_schedule_space_exhausted")

    def _successors(self, fixture: PairedFixture) -> list[PairedFixture]:
        successors: list[PairedFixture] = []
        committed = {message.identity() for message in fixture.state.source.committed_messages}
        for message in self.messages:
            if message.identity() in committed and not fixture.profile.allow_duplicate_enqueue:
                continue
            branch = self._clone(fixture)
            try:
                branch.enqueue(message)
            except ValueError:
                continue
            successors.append(branch)
        for index in range(len(fixture.state.pending)):
            branch = self._clone(fixture)
            try:
                branch.deliver(index)
            except (IndexError, ValueError):
                continue
            successors.append(branch)
        if fixture.profile.allow_pre_finality_reorg:
            branch = self._clone(fixture)
            try:
                branch.reorg_latest()
            except ValueError:
                pass
            else:
                successors.append(branch)
        return successors

    @staticmethod
    def _clone(fixture: PairedFixture) -> PairedFixture:
        clone = PairedFixture(
            fixture.state.source.domain,
            fixture.state.destination.domain,
            bounds=fixture.bounds,
            profile=fixture.profile,
        )
        clone.restore(fixture.snapshot())
        return clone

    @staticmethod
    def _fingerprint(fixture: PairedFixture) -> str:
        state = fixture.state
        return sha256_hex(
            {
                "source": BoundedPairedExplorer._chain_value(state.source),
                "destination": BoundedPairedExplorer._chain_value(state.destination),
                "pending": [BoundedPairedExplorer._message_value(message) for message in state.pending],
                "delivered": [BoundedPairedExplorer._message_value(message) for message in state.delivered],
                "clocks": state.clocks,
                "observer_state": state.observer_state,
                "transaction_count": state.transaction_count,
                "channel_transition_count": state.channel_transition_count,
                "action_log": [
                    {
                        "action": event.action.value,
                        "message": BoundedPairedExplorer._message_value(event.message),
                        "transaction_index": event.transaction_index,
                        "channel_transition_index": event.channel_transition_index,
                        "pending_before": event.pending_before,
                        "pending_after": event.pending_after,
                    }
                    for event in state.action_log
                ],
                "remaining_transactions": fixture.bounds.max_transactions - state.transaction_count,
                "remaining_channel_transitions": (
                    fixture.bounds.max_channel_transitions - state.channel_transition_count
                ),
                "canonical_history": {
                    "source": list(state.source.canonical_history),
                    "destination": list(state.destination.canonical_history),
                },
            }
        )

    @staticmethod
    def _chain_value(chain: object) -> dict[str, object]:
        # ``chain`` is structurally a ChainState; keeping the serializer local
        # avoids making it an artifact/public-record schema prematurely.
        return {
            "domain": chain.domain,  # type: ignore[attr-defined]
            "storage": chain.storage,  # type: ignore[attr-defined]
            "committed_messages": [
                BoundedPairedExplorer._message_value(message)
                for message in chain.committed_messages  # type: ignore[attr-defined]
            ],
        }

    @staticmethod
    def _message_value(message: Message) -> dict[str, object]:
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
