from __future__ import annotations

import unittest
import z3

from crossllm.backends import (
    SymbolicPairedExplorer,
    SymbolicSearchControl,
)
from crossllm.contracts import SearchStatus
from crossllm.semantics import Message, PairedFixture, TransitionBounds, TransitionProfile


def message(nonce: int) -> Message:
    return Message("source", "destination", "bridge", "receiver", nonce, f"commit-{nonce}")


class SymbolicPairedTests(unittest.TestCase):
    def test_symbolic_reordering_model_is_replayed_as_a_native_witness(self) -> None:
        result = SymbolicPairedExplorer([message(1), message(2)]).search(
            PairedFixture(bounds=TransitionBounds(4, 4, 2)),
            lambda state: (
                state.source.committed_messages == [message(1), message(2)]
                and state.transaction_count == 3
                and bool(state.delivered)
                and state.delivered[0].nonce == 2
                and any(item.nonce == 1 for item in state.pending)
            ),
        )
        self.assertEqual(result.status, SearchStatus.SAT)
        self.assertTrue(result.complete)
        self.assertEqual(len(result.witness), 3)
        self.assertEqual(result.witness[-1].action.value, "deliver")
        self.assertEqual(result.witness[-1].message.nonce, 2)
        self.assertEqual(len(result.encoding_hash), 64)

    def test_symbolic_unsat_requires_schedule_exhaustion(self) -> None:
        result = SymbolicPairedExplorer([message(1), message(2)]).search(
            PairedFixture(bounds=TransitionBounds(4, 4, 2)),
            lambda _state: False,
        )
        self.assertEqual(result.status, SearchStatus.BOUNDED_UNSAT)
        self.assertTrue(result.complete)
        self.assertEqual(result.reason, "finite_symbolic_schedule_space_exhausted")
        self.assertGreater(result.explored_states, 0)

    def test_profile_controls_fifo_duplicate_reorg_and_attestation(self) -> None:
        fifo = SymbolicPairedExplorer([message(1), message(2)]).search(
            PairedFixture(
                bounds=TransitionBounds(3, 3, 2),
                profile=TransitionProfile(allow_reordering=False),
            ),
            lambda state: (
                state.source.committed_messages[:2] == [message(1), message(2)]
                and bool(state.delivered)
                and state.delivered[0].nonce == 2
                and any(item.nonce == 1 for item in state.pending)
            ),
        )
        self.assertEqual(fifo.status, SearchStatus.BOUNDED_UNSAT)

        duplicate = SymbolicPairedExplorer([message(1)]).search(
            PairedFixture(
                bounds=TransitionBounds(2, 2, 2),
                profile=TransitionProfile(allow_duplicate_enqueue=True),
            ),
            lambda state: len(state.pending) == 2,
        )
        self.assertEqual(duplicate.status, SearchStatus.SAT)
        self.assertEqual([event.action.value for event in duplicate.witness], ["enqueue", "enqueue"])

        reorg = SymbolicPairedExplorer([message(1)]).search(
            PairedFixture(
                bounds=TransitionBounds(3, 2, 1),
                profile=TransitionProfile(allow_pre_finality_reorg=True, finality_depth=1),
            ),
            lambda state: not state.source.committed_messages and state.transaction_count == 2,
        )
        self.assertEqual(reorg.status, SearchStatus.SAT)
        self.assertEqual([event.action.value for event in reorg.witness], ["enqueue", "reorg"])

        attested = SymbolicPairedExplorer([message(1)]).search(
            PairedFixture(
                profile=TransitionProfile(
                    require_attestation=True,
                    authorized_emitters=("bridge",),
                    authorized_attestors=("watcher",),
                ),
            ),
            lambda state: bool(state.pending),
        )
        self.assertEqual(attested.status, SearchStatus.BOUNDED_UNSAT)

    def test_operational_limits_and_unsupported_initial_state_are_not_proofs(self) -> None:
        limited = SymbolicPairedExplorer([message(1), message(2)]).search(
            PairedFixture(bounds=TransitionBounds(4, 4, 2)),
            lambda _state: False,
            control=SymbolicSearchControl(max_models=1),
        )
        self.assertEqual(limited.status, SearchStatus.UNKNOWN)
        self.assertFalse(limited.complete)
        self.assertEqual(limited.reason, "model_limit_exhausted")

        cancelled = SymbolicPairedExplorer([message(1)]).search(
            PairedFixture(), lambda _state: False, cancelled=lambda: True
        )
        self.assertEqual(cancelled.status, SearchStatus.UNKNOWN)
        self.assertFalse(cancelled.complete)
        self.assertEqual(cancelled.reason, "cancelled")

    def test_prior_campaign_work_consumes_shared_deadline(self) -> None:
        result = SymbolicPairedExplorer([message(1)]).search(
            PairedFixture(bounds=TransitionBounds(2, 2, 1)),
            lambda _state: False,
            control=SymbolicSearchControl(
                query_timeout_seconds=10.0,
                campaign_deadline_seconds=10.0,
                campaign_elapsed_seconds=10.0,
            ),
        )
        self.assertEqual(result.status, SearchStatus.TIMEOUT)
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "campaign_deadline")

    def test_predicate_error_is_not_reported_as_bounded_unsat(self) -> None:
        result = SymbolicPairedExplorer([message(1)]).search(
            PairedFixture(),
            lambda _state: (_ for _ in ()).throw(RuntimeError("property unavailable")),
        )
        self.assertEqual(result.status, SearchStatus.CRASH)
        self.assertFalse(result.complete)
        self.assertIn("predicate_error:RuntimeError", result.reason or "")

    def test_symbolic_decoder_rejects_missing_assignment_without_completion(self) -> None:
        explorer = SymbolicPairedExplorer([message(1)])
        encoding = explorer._encode(PairedFixture(bounds=TransitionBounds(2, 2, 1)))

        class PartialModel:
            def eval(self, variable, *, model_completion=False):
                self_seen = variable.decl().name()
                if self_seen == "action_kind_0":
                    return z3.IntVal(1)
                return variable

        with self.assertRaisesRegex(ValueError, "missing assignment"):
            explorer._decode(PartialModel(), encoding)  # type: ignore[arg-type]

    def test_symbolic_decoder_rejects_out_of_range_message_index(self) -> None:
        explorer = SymbolicPairedExplorer([message(1)])
        encoding = explorer._encode(PairedFixture(bounds=TransitionBounds(2, 2, 1)))

        class InvalidModel:
            def eval(self, variable, *, model_completion=False):
                name = variable.decl().name()
                if name == "action_kind_0":
                    return z3.IntVal(1)
                if name == "action_message_0":
                    return z3.IntVal(1)
                return z3.IntVal(0)

        with self.assertRaisesRegex(ValueError, "out of bounds"):
            explorer._decode(InvalidModel(), encoding)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
