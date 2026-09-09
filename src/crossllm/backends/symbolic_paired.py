"""Symbolic bounded transition search for the paired-chain fixture.

This backend is intentionally separate from :mod:`paired_explorer`.  Z3
encodes the finite channel transition relation; every model is then replayed
through the native fixture before a user supplied state predicate is evaluated.
That replay is a differential guard, not an EVM implementation or a security
correctness oracle.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable

import z3

from ..contracts.canonical import sha256_hex
from ..contracts.records import SearchStatus
from ..semantics import Action, ActionRecord, DualChainState, Message, PairedFixture
from .solver_control import check_solver


StatePredicate = Callable[[DualChainState], bool]
Cancellation = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class SymbolicSearchControl:
    """Operational limits for one symbolic bounded query."""

    query_timeout_seconds: float = 30.0
    campaign_deadline_seconds: float = 3600.0
    campaign_elapsed_seconds: float = 0.0
    max_models: int = 100_000

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
        if self.max_models <= 0:
            raise ValueError("max_models must be positive")

    def remaining_seconds(self) -> float:
        return min(
            self.query_timeout_seconds,
            max(0.0, self.campaign_deadline_seconds - self.campaign_elapsed_seconds),
        )

    def expiration_reason(self, elapsed_seconds: float) -> str:
        if self.campaign_elapsed_seconds + elapsed_seconds >= self.campaign_deadline_seconds:
            return "campaign_deadline"
        return "query_timeout"


@dataclass(frozen=True, slots=True)
class SymbolicSearchResult:
    """Finite symbolic-search result with explicit completeness metadata."""

    status: SearchStatus
    explored_states: int
    explored_paths: int
    schedule_count: int
    complete: bool
    reason: str | None = None
    witness: tuple[ActionRecord, ...] = ()
    elapsed_seconds: float = 0.0
    cache_hits: int = 0
    solver: str = "z3"
    encoding_hash: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "explored_states": self.explored_states,
            "explored_paths": self.explored_paths,
            "schedule_count": self.schedule_count,
            "complete": self.complete,
            "reason": self.reason,
            "witness_length": len(self.witness),
            "elapsed_seconds": self.elapsed_seconds,
            "cache_hits": self.cache_hits,
            "solver": self.solver,
            "encoding_hash": self.encoding_hash,
        }


@dataclass(frozen=True, slots=True)
class _Encoding:
    solver: z3.Solver
    kinds: tuple[z3.IntNumRef | z3.ArithRef, ...]
    selected: tuple[z3.IntNumRef | z3.ArithRef, ...]
    steps: int
    encoding_hash: str


class SymbolicPairedExplorer:
    """Encode and exhaustively enumerate the finite paired transition space.

    The symbolic state uses bounded ordered arrays for the pending queue,
    source canonical message history, and destination delivery history.  This
    makes FIFO and adversarial reordering distinct relations and also permits
    duplicate enqueue when the profile explicitly enables it.  Initial
    arbitrary storage and observer state are preserved by the native replay;
    all actions in this core only mutate the represented histories/clocks.
    """

    _NOOP = 0
    _ENQUEUE = 1
    _DELIVER = 2
    _REORG = 3

    def __init__(self, messages: tuple[Message, ...] | list[Message], *, max_models: int = 100_000) -> None:
        if max_models <= 0:
            raise ValueError("max_models must be positive")
        self.messages = tuple(messages)
        if len({message.identity() for message in self.messages}) != len(self.messages):
            raise ValueError("candidate messages must have unique identities")
        self.max_models = max_models

    def search(
        self,
        fixture: PairedFixture,
        violation: StatePredicate,
        *,
        control: SymbolicSearchControl | None = None,
        cancelled: Cancellation | None = None,
    ) -> SymbolicSearchResult:
        control = control or SymbolicSearchControl(max_models=self.max_models)
        started = time.monotonic()
        encoding_hash = ""
        try:
            encoding = self._encode(fixture)
            encoding_hash = encoding.encoding_hash
        except ValueError as error:
            return self._result(
                SearchStatus.UNSUPPORTED,
                False,
                str(error),
                started,
                encoding_hash,
                0,
                0,
            )

        explored = 0
        initial = self._clone(fixture)
        try:
            initial_is_violation = self._predicate(violation, initial.state)
        except Exception as error:
            return self._result(
                SearchStatus.CRASH,
                False,
                f"predicate_error:{type(error).__name__}:{error}",
                started,
                encoding_hash,
                explored,
                0,
            )
        if initial_is_violation:
            return self._result(
                SearchStatus.SAT,
                True,
                "predicate_satisfied_at_initial_state",
                started,
                encoding_hash,
                explored,
                0,
                (),
            )

        while True:
            if cancelled is not None:
                try:
                    if cancelled():
                        return self._result(SearchStatus.UNKNOWN, False, "cancelled", started, encoding_hash, explored, explored)
                except Exception as error:
                    return self._result(SearchStatus.CRASH, False, f"cancellation_error:{error}", started, encoding_hash, explored, explored)
            elapsed = time.monotonic() - started
            query_budget = control.remaining_seconds()
            if query_budget <= 0:
                return self._result(SearchStatus.TIMEOUT, False, "campaign_deadline", started, encoding_hash, explored, explored)
            if elapsed >= query_budget:
                return self._result(SearchStatus.TIMEOUT, False, control.expiration_reason(elapsed), started, encoding_hash, explored, explored)
            if explored >= control.max_models:
                return self._result(SearchStatus.UNKNOWN, False, "model_limit_exhausted", started, encoding_hash, explored, explored)

            remaining = query_budget - elapsed
            encoding.solver.set(timeout=max(1, int(remaining * 1000)))
            try:
                solver_check = check_solver(encoding.solver, cancelled)
            except z3.Z3Exception as error:
                return self._result(SearchStatus.CRASH, False, f"solver_error:{error}", started, encoding_hash, explored, explored)
            if solver_check.callback_error is not None:
                return self._result(
                    SearchStatus.CRASH,
                    False,
                    f"cancellation_error:{solver_check.callback_error}",
                    started,
                    encoding_hash,
                    explored,
                    explored,
                )
            if solver_check.interrupted:
                return self._result(SearchStatus.UNKNOWN, False, "cancelled", started, encoding_hash, explored, explored)
            outcome = solver_check.result
            if outcome == z3.unsat:
                return self._result(
                    SearchStatus.BOUNDED_UNSAT,
                    True,
                    "finite_symbolic_schedule_space_exhausted",
                    started,
                    encoding_hash,
                    explored,
                    explored,
                )
            if outcome != z3.sat:
                elapsed = time.monotonic() - started
                solver_reason = encoding.solver.reason_unknown() or "solver_unknown"
                if elapsed >= query_budget or "timeout" in solver_reason.lower():
                    return self._result(
                        SearchStatus.TIMEOUT,
                        False,
                        control.expiration_reason(elapsed),
                        started,
                        encoding_hash,
                        explored,
                        explored,
                    )
                return self._result(
                    SearchStatus.UNKNOWN,
                    False,
                    solver_reason,
                    started,
                    encoding_hash,
                    explored,
                    explored,
                )

            model = encoding.solver.model()
            try:
                actions = self._decode(model, encoding)
            except (TypeError, ValueError) as error:
                return self._result(SearchStatus.CRASH, False, f"model_decode_error:{error}", started, encoding_hash, explored, explored)
            explored += 1
            replay = self._replay(fixture, actions)
            if replay is None:
                return self._result(
                    SearchStatus.CRASH,
                    False,
                    "symbolic_native_transition_mismatch",
                    started,
                    encoding_hash,
                    explored,
                    explored,
                )
            for index, state in replay:
                try:
                    is_violation = self._predicate(violation, state)
                except Exception as error:
                    return self._result(
                        SearchStatus.CRASH,
                        False,
                        f"predicate_error:{type(error).__name__}:{error}",
                        started,
                        encoding_hash,
                        explored,
                        explored,
                    )
                if is_violation:
                    # Reconstruct the exact prefix from a second native replay;
                    # this keeps the result's evidence in the fixture's type.
                    witness = self._prefix_witness(fixture, actions, index)
                    return self._result(
                        SearchStatus.SAT,
                        True,
                        "symbolic_model_replayed",
                        started,
                        encoding_hash,
                        explored,
                        explored,
                        witness,
                    )
            self._block_model(encoding, model)

    def _encode(self, fixture: PairedFixture) -> _Encoding:
        self._validate_initial(fixture)
        message_count = len(self.messages)
        steps = max(0, fixture.bounds.max_transactions - fixture.state.transaction_count)
        solver = z3.Solver()
        kinds = tuple(z3.Int(f"action_kind_{step}") for step in range(steps))
        selected = tuple(z3.Int(f"action_message_{step}") for step in range(steps))
        for step in range(steps):
            solver.add(kinds[step] >= self._NOOP, kinds[step] <= self._REORG)
            solver.add(selected[step] >= -1, selected[step] < message_count)
            solver.add(z3.Implies(kinds[step] == self._NOOP, selected[step] == -1))
            solver.add(z3.Implies(kinds[step] != self._NOOP, selected[step] >= 0))
            if step:
                solver.add(z3.Implies(kinds[step - 1] == self._NOOP, kinds[step] == self._NOOP))

        pending_count = [z3.Int(f"pending_count_{step}") for step in range(steps + 1)]
        committed_count = [z3.Int(f"committed_count_{step}") for step in range(steps + 1)]
        delivered_count = [z3.Int(f"delivered_count_{step}") for step in range(steps + 1)]
        transaction_count = [z3.Int(f"tx_count_{step}") for step in range(steps + 1)]
        channel_count = [z3.Int(f"channel_count_{step}") for step in range(steps + 1)]
        source_clock = [z3.Int(f"source_clock_{step}") for step in range(steps + 1)]
        destination_clock = [z3.Int(f"destination_clock_{step}") for step in range(steps + 1)]
        pending = self._arrays("pending", steps, fixture.bounds.max_pending)
        committed = self._arrays("committed", steps, fixture.bounds.max_transactions)
        delivered = self._arrays("delivered", steps, fixture.bounds.max_transactions)

        self._initial_constraints(
            solver, fixture, pending_count, committed_count, delivered_count,
            transaction_count, channel_count, source_clock, destination_clock,
            pending, committed, delivered,
        )
        for step in range(steps):
            self._transition_constraints(
                solver, fixture, step, kinds[step], selected[step],
                pending_count, committed_count, delivered_count,
                transaction_count, channel_count, source_clock, destination_clock,
                pending, committed, delivered,
            )
        encoding_hash = sha256_hex({
            "encoding": "ordered-array-paired-transition-v1",
            "messages": [self._message_value(message) for message in self.messages],
            "bounds": {
                "max_transactions": fixture.bounds.max_transactions,
                "max_channel_transitions": fixture.bounds.max_channel_transitions,
                "max_pending": fixture.bounds.max_pending,
            },
            "profile": {
                "allow_reordering": fixture.profile.allow_reordering,
                "allow_duplicate_enqueue": fixture.profile.allow_duplicate_enqueue,
                "allow_pre_finality_reorg": fixture.profile.allow_pre_finality_reorg,
                "finality_depth": fixture.profile.finality_depth,
                "require_attestation": fixture.profile.require_attestation,
                "authorized_emitters": fixture.profile.authorized_emitters,
                "authorized_attestors": fixture.profile.authorized_attestors,
            },
            "steps": steps,
        })
        return _Encoding(solver, kinds, selected, steps, encoding_hash)

    @staticmethod
    def _arrays(prefix: str, steps: int, width: int) -> list[list[z3.ArithRef]]:
        return [[z3.Int(f"{prefix}_{step}_{slot}") for slot in range(width)] for step in range(steps + 1)]

    def _initial_constraints(
        self,
        solver: z3.Solver,
        fixture: PairedFixture,
        pending_count: list[z3.ArithRef],
        committed_count: list[z3.ArithRef],
        delivered_count: list[z3.ArithRef],
        transaction_count: list[z3.ArithRef],
        channel_count: list[z3.ArithRef],
        source_clock: list[z3.ArithRef],
        destination_clock: list[z3.ArithRef],
        pending: list[list[z3.ArithRef]],
        committed: list[list[z3.ArithRef]],
        delivered: list[list[z3.ArithRef]],
    ) -> None:
        state = fixture.state
        solver.add(pending_count[0] == len(state.pending))
        solver.add(committed_count[0] == len(state.source.committed_messages))
        solver.add(delivered_count[0] == len(state.delivered))
        solver.add(transaction_count[0] == state.transaction_count)
        solver.add(channel_count[0] == state.channel_transition_count)
        solver.add(source_clock[0] == state.clocks.get(state.source.domain, 0))
        solver.add(destination_clock[0] == state.clocks.get(state.destination.domain, 0))
        self._pin_values(solver, pending[0], self._indices(state.pending))
        self._pin_values(solver, committed[0], self._indices(state.source.committed_messages))
        self._pin_values(solver, delivered[0], self._indices(state.delivered))
        for step in range(len(pending)):
            solver.add(pending_count[step] >= 0, pending_count[step] <= fixture.bounds.max_pending)
            solver.add(committed_count[step] >= 0, committed_count[step] <= fixture.bounds.max_transactions)
            solver.add(delivered_count[step] >= 0, delivered_count[step] <= fixture.bounds.max_transactions)
            solver.add(transaction_count[step] >= 0, transaction_count[step] <= fixture.bounds.max_transactions)
            solver.add(channel_count[step] >= 0, channel_count[step] <= fixture.bounds.max_channel_transitions)

    @staticmethod
    def _pin_values(solver: z3.Solver, variables: list[z3.ArithRef], values: list[int]) -> None:
        for index, variable in enumerate(variables):
            solver.add(variable == (values[index] if index < len(values) else -1))

    def _transition_constraints(
        self,
        solver: z3.Solver,
        fixture: PairedFixture,
        step: int,
        kind: z3.ArithRef,
        selected: z3.ArithRef,
        pending_count: list[z3.ArithRef],
        committed_count: list[z3.ArithRef],
        delivered_count: list[z3.ArithRef],
        transaction_count: list[z3.ArithRef],
        channel_count: list[z3.ArithRef],
        source_clock: list[z3.ArithRef],
        destination_clock: list[z3.ArithRef],
        pending: list[list[z3.ArithRef]],
        committed: list[list[z3.ArithRef]],
        delivered: list[list[z3.ArithRef]],
    ) -> None:
        before_pending, after_pending = pending[step], pending[step + 1]
        before_committed, after_committed = committed[step], committed[step + 1]
        before_delivered, after_delivered = delivered[step], delivered[step + 1]
        no_op = kind == self._NOOP
        enqueue = kind == self._ENQUEUE
        deliver = kind == self._DELIVER
        reorg = kind == self._REORG
        self._frame_when(solver, no_op, pending_count[step], pending_count[step + 1])
        self._frame_when(solver, no_op, committed_count[step], committed_count[step + 1])
        self._frame_when(solver, no_op, delivered_count[step], delivered_count[step + 1])
        self._frame_when(solver, no_op, transaction_count[step], transaction_count[step + 1])
        self._frame_when(solver, no_op, channel_count[step], channel_count[step + 1])
        self._frame_when(solver, no_op, source_clock[step], source_clock[step + 1])
        self._frame_when(solver, no_op, destination_clock[step], destination_clock[step + 1])
        for before, after in (
            (before_pending, after_pending), (before_committed, after_committed),
            (before_delivered, after_delivered),
        ):
            for left, right in zip(before, after):
                self._frame_when(solver, no_op, left, right)

        # Enqueue appends a candidate message to pending and source history.
        enqueue_valid = z3.And(
            pending_count[step] < fixture.bounds.max_pending,
            transaction_count[step] < fixture.bounds.max_transactions,
            channel_count[step] < fixture.bounds.max_channel_transitions,
            self._candidate_allowed(selected, fixture),
        )
        if not fixture.profile.allow_duplicate_enqueue:
            enqueue_valid = z3.And(enqueue_valid, *[
                z3.And(z3.Implies(before_committed[slot] == index, selected != index))
                for slot in range(fixture.bounds.max_transactions)
                for index in range(len(self.messages))
            ])
        solver.add(z3.Implies(enqueue, enqueue_valid))
        self._append_relation(solver, enqueue, pending_count[step], pending_count[step + 1], before_pending, after_pending, selected)
        self._append_relation(solver, enqueue, committed_count[step], committed_count[step + 1], before_committed, after_committed, selected)
        self._frame_when(solver, enqueue, delivered_count[step], delivered_count[step + 1])
        self._frame_array_when(solver, enqueue, before_delivered, after_delivered)
        self._increment_when(solver, enqueue, transaction_count[step], transaction_count[step + 1])
        self._increment_when(solver, enqueue, channel_count[step], channel_count[step + 1])
        solver.add(z3.Implies(enqueue, source_clock[step + 1] == source_clock[step] + 1))
        self._frame_when(solver, enqueue, destination_clock[step], destination_clock[step + 1])

        # Delivery removes the selected pending entry and appends it to the
        # destination history.  ``allow_reordering=False`` is strict FIFO.
        pending_has_selected = self._contains(before_pending, pending_count[step], selected)
        delivery_valid = z3.And(
            pending_count[step] > 0,
            transaction_count[step] < fixture.bounds.max_transactions,
            channel_count[step] < fixture.bounds.max_channel_transitions,
            pending_has_selected,
        )
        if not fixture.profile.allow_reordering:
            delivery_valid = z3.And(delivery_valid, before_pending[0] == selected)
        solver.add(z3.Implies(deliver, delivery_valid))
        self._remove_relation(solver, deliver, pending_count[step], pending_count[step + 1], before_pending, after_pending, selected)
        self._frame_when(solver, deliver, committed_count[step], committed_count[step + 1])
        self._frame_array_when(solver, deliver, before_committed, after_committed)
        self._append_relation(solver, deliver, delivered_count[step], delivered_count[step + 1], before_delivered, after_delivered, selected)
        self._increment_when(solver, deliver, transaction_count[step], transaction_count[step + 1])
        self._increment_when(solver, deliver, channel_count[step], channel_count[step + 1])
        self._frame_when(solver, deliver, source_clock[step], source_clock[step + 1])
        solver.add(z3.Implies(deliver, destination_clock[step + 1] == destination_clock[step] + 1))

        # Reorg removes the latest committed message, provided that it is
        # still pending.  Channel transitions do not count a reorg as enqueue
        # or delivery, matching PairedFixture._record_action.
        reorg_valid = z3.BoolVal(fixture.profile.allow_pre_finality_reorg)
        reorg_valid = z3.And(
            reorg_valid,
            committed_count[step] > 0,
            transaction_count[step] < fixture.bounds.max_transactions,
            self._latest_is_selected(before_committed, committed_count[step], selected),
            pending_has_selected,
        )
        solver.add(z3.Implies(reorg, reorg_valid))
        self._remove_last_relation(solver, reorg, committed_count[step], committed_count[step + 1], before_committed, after_committed)
        self._remove_last_relation(solver, reorg, pending_count[step], pending_count[step + 1], before_pending, after_pending, selected)
        self._frame_array_when(solver, reorg, before_delivered, after_delivered)
        self._increment_when(solver, reorg, transaction_count[step], transaction_count[step + 1])
        self._frame_when(solver, reorg, channel_count[step], channel_count[step + 1])
        solver.add(z3.Implies(reorg, source_clock[step + 1] == source_clock[step] - 1))
        self._frame_when(solver, reorg, destination_clock[step], destination_clock[step + 1])

        # A valid non-NOOP action must take exactly one recognized branch.
        solver.add(z3.Implies(kind != self._NOOP, z3.Or(enqueue, deliver, reorg)))

    @staticmethod
    def _frame_when(solver: z3.Solver, condition: z3.BoolRef, before: z3.ArithRef, after: z3.ArithRef) -> None:
        solver.add(z3.Implies(condition, after == before))

    @staticmethod
    def _increment_when(solver: z3.Solver, condition: z3.BoolRef, before: z3.ArithRef, after: z3.ArithRef) -> None:
        solver.add(z3.Implies(condition, after == before + 1))

    @staticmethod
    def _frame_array_when(solver: z3.Solver, condition: z3.BoolRef, before: list[z3.ArithRef], after: list[z3.ArithRef]) -> None:
        for left, right in zip(before, after):
            solver.add(z3.Implies(condition, right == left))

    @staticmethod
    def _append_relation(
        solver: z3.Solver,
        condition: z3.BoolRef,
        count_before: z3.ArithRef,
        count_after: z3.ArithRef,
        before: list[z3.ArithRef],
        after: list[z3.ArithRef],
        selected: z3.ArithRef,
    ) -> None:
        solver.add(z3.Implies(condition, count_after == count_before + 1))
        for slot, (left, right) in enumerate(zip(before, after)):
            solver.add(z3.Implies(
                condition,
                z3.If(
                    slot < count_before,
                    right == left,
                    z3.If(slot == count_before, right == selected, right == -1),
                ),
            ))

    @staticmethod
    def _remove_relation(
        solver: z3.Solver,
        condition: z3.BoolRef,
        count_before: z3.ArithRef,
        count_after: z3.ArithRef,
        before: list[z3.ArithRef],
        after: list[z3.ArithRef],
        selected: z3.ArithRef,
    ) -> None:
        solver.add(z3.Implies(condition, count_after == count_before - 1))
        # Delivery removes the first matching queue entry.  Express the
        # selected position symbolically so duplicate queues remain exact.
        first_matches = [
            z3.And(
                position < count_before,
                before[position] == selected,
                *[before[prior] != selected for prior in range(position)],
            )
            for position in range(len(before))
        ]
        solver.add(z3.Implies(condition, z3.Or(*first_matches)))
        for slot, right in enumerate(after):
            choices = []
            for position, first_match in enumerate(first_matches):
                shifted = before[slot + 1] if slot + 1 < len(before) else z3.IntVal(-1)
                target = z3.If(slot < position, before[slot], z3.If(slot < count_before - 1, shifted, -1))
                choices.append(z3.And(first_match, right == target))
            solver.add(z3.Implies(condition, z3.Or(*choices)))

    @staticmethod
    def _remove_last_relation(
        solver: z3.Solver,
        condition: z3.BoolRef,
        count_before: z3.ArithRef,
        count_after: z3.ArithRef,
        before: list[z3.ArithRef],
        after: list[z3.ArithRef],
        selected: z3.ArithRef | None = None,
    ) -> None:
        solver.add(z3.Implies(condition, count_after == count_before - 1))
        if selected is None:
            last_matches = [z3.And(count_before == position + 1) for position in range(len(before))]
        else:
            last_matches = [
                z3.And(
                    position < count_before,
                    before[position] == selected,
                    *[before[later] != selected for later in range(position + 1, len(before))],
                )
                for position in range(len(before))
            ]
        solver.add(z3.Implies(condition, z3.Or(*last_matches)))
        for slot, right in enumerate(after):
            choices = []
            for position, last_match in enumerate(last_matches):
                shifted = before[slot + 1] if slot + 1 < len(before) else z3.IntVal(-1)
                target = z3.If(slot < position, before[slot], z3.If(slot < count_before - 1, shifted, -1))
                choices.append(z3.And(last_match, right == target))
            solver.add(z3.Implies(condition, z3.Or(*choices)))

    @staticmethod
    def _contains(array: list[z3.ArithRef], count: z3.ArithRef, selected: z3.ArithRef) -> z3.BoolRef:
        return z3.Or(*[z3.And(slot < count, value == selected) for slot, value in enumerate(array)])

    @staticmethod
    def _latest_is_selected(array: list[z3.ArithRef], count: z3.ArithRef, selected: z3.ArithRef) -> z3.BoolRef:
        return z3.Or(*[z3.And(count == slot + 1, array[slot] == selected) for slot in range(len(array))])

    def _candidate_allowed(self, selected: z3.ArithRef, fixture: PairedFixture) -> z3.BoolRef:
        allowed = []
        for index, message in enumerate(self.messages):
            valid = (
                message.source_domain == fixture.state.source.domain
                and message.destination_domain == fixture.state.destination.domain
                and message.nonce >= 0
                and bool(message.emitter and message.recipient and message.payload_commitment)
                and (message.intent_id is None or bool(message.intent_id))
            )
            if fixture.profile.authorized_emitters:
                valid = valid and message.emitter in fixture.profile.authorized_emitters
            if fixture.profile.require_attestation:
                valid = valid and bool(message.attestation and message.attestor and message.attestor in fixture.profile.authorized_attestors)
            elif message.attestation is not None:
                valid = valid and bool(message.attestation)
            allowed.append(z3.And(selected == index, z3.BoolVal(valid)))
        return z3.Or(*allowed) if allowed else z3.BoolVal(False)

    def _decode(self, model: z3.ModelRef, encoding: _Encoding) -> tuple[tuple[Action, int], ...]:
        result: list[tuple[Action, int]] = []
        saw_noop = False
        for kind_variable, selected_variable in zip(encoding.kinds, encoding.selected):
            kind_value = model.eval(kind_variable, model_completion=False)
            selected_value = model.eval(selected_variable, model_completion=False)
            if not z3.is_int_value(kind_value):
                raise ValueError(f"missing assignment for {kind_variable.decl().name()}")
            if not z3.is_int_value(selected_value):
                raise ValueError(f"missing assignment for {selected_variable.decl().name()}")
            kind = kind_value.as_long()
            selected = selected_value.as_long()
            if saw_noop:
                if kind != self._NOOP or selected != -1:
                    raise ValueError("symbolic assignment has an action after NOOP")
                continue
            if kind == self._NOOP:
                if selected != -1:
                    raise ValueError("NOOP assignment must select message -1")
                saw_noop = True
                continue
            if selected < 0 or selected >= len(self.messages):
                raise ValueError("symbolic assignment message index is out of bounds")
            action = {
                self._ENQUEUE: Action.ENQUEUE,
                self._DELIVER: Action.DELIVER,
                self._REORG: Action.REORG,
            }.get(kind)
            if action is None:
                raise ValueError("symbolic model contains an unknown action kind")
            result.append((action, selected))
        return tuple(result)

    def _replay(self, fixture: PairedFixture, actions: tuple[tuple[Action, int], ...]) -> list[tuple[int, DualChainState]] | None:
        replay = self._clone(fixture)
        states: list[tuple[int, DualChainState]] = [(0, replay.snapshot())]
        try:
            for index, (action, message_index) in enumerate(actions, 1):
                message = self.messages[message_index]
                if action is Action.ENQUEUE:
                    replay.enqueue(message)
                elif action is Action.DELIVER:
                    pending_index = next(
                        position for position, pending in enumerate(replay.state.pending)
                        if pending.identity() == message.identity()
                    )
                    replay.deliver(pending_index)
                elif action is Action.REORG:
                    replay.reorg_latest()
                else:
                    raise ValueError("unknown symbolic action")
                states.append((index, replay.snapshot()))
        except (IndexError, StopIteration, TypeError, ValueError):
            return None
        return states

    def _prefix_witness(
        self,
        fixture: PairedFixture,
        actions: tuple[tuple[Action, int], ...],
        prefix_length: int,
    ) -> tuple[ActionRecord, ...]:
        replay = self._clone(fixture)
        for action, message_index in actions[:prefix_length]:
            message = self.messages[message_index]
            if action is Action.ENQUEUE:
                replay.enqueue(message)
            elif action is Action.DELIVER:
                pending_index = next(
                    position for position, pending in enumerate(replay.state.pending)
                    if pending.identity() == message.identity()
                )
                replay.deliver(pending_index)
            else:
                replay.reorg_latest()
        return tuple(replay.state.action_log)

    @staticmethod
    def _block_model(encoding: _Encoding, model: z3.ModelRef) -> None:
        encoding.solver.add(z3.Or(*[
            z3.Or(
                kind != model.eval(kind, model_completion=True),
                selected != model.eval(selected, model_completion=True),
            )
            for kind, selected in zip(encoding.kinds, encoding.selected)
        ]))

    def _validate_initial(self, fixture: PairedFixture) -> None:
        if fixture.state.transaction_count > fixture.bounds.max_transactions:
            raise ValueError("initial transaction count exceeds bound")
        if fixture.state.channel_transition_count > fixture.bounds.max_channel_transitions:
            raise ValueError("initial channel transition count exceeds bound")
        if len(fixture.state.pending) > fixture.bounds.max_pending:
            raise ValueError("initial pending queue exceeds bound")
        if len(fixture.state.source.committed_messages) > fixture.bounds.max_transactions:
            raise ValueError("initial committed history exceeds bound")
        if len(fixture.state.delivered) > fixture.bounds.max_transactions:
            raise ValueError("initial delivered history exceeds bound")
        for message in (
            *fixture.state.pending,
            *fixture.state.source.committed_messages,
            *fixture.state.delivered,
        ):
            if message.identity() not in {candidate.identity() for candidate in self.messages}:
                raise ValueError("initial state contains a message outside candidate domain")
        if fixture.profile.allow_pre_finality_reorg and fixture.profile.finality_depth < 1:
            raise ValueError("pre-finality reorg requires positive finality depth")

    def _indices(self, messages: list[Message]) -> list[int]:
        indices = {message.identity(): index for index, message in enumerate(self.messages)}
        return [indices[message.identity()] for message in messages]

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
    def _predicate(predicate: StatePredicate, state: DualChainState) -> bool:
        """Evaluate a property without converting evaluator errors to ``False``.

        Callers turn an exception into a non-complete ``CRASH`` result. This
        distinction is required for fail-closed bounded-unsat reporting.
        """
        return bool(predicate(state))

    def _result(
        self,
        status: SearchStatus,
        complete: bool,
        reason: str | None,
        started: float,
        encoding_hash: str,
        explored_states: int,
        explored_paths: int,
        witness: tuple[ActionRecord, ...] = (),
    ) -> SymbolicSearchResult:
        return SymbolicSearchResult(
            status, explored_states, explored_paths, explored_paths,
            complete, reason, witness, max(0.0, time.monotonic() - started), 0,
            f"z3-{z3.get_version_string()}", encoding_hash,
        )

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


__all__ = ["SymbolicPairedExplorer", "SymbolicSearchControl", "SymbolicSearchResult"]
