from __future__ import annotations

import unittest

from crossllm.backends import BoundedPairedExplorer, SearchControl
from crossllm.contracts import SearchStatus
from crossllm.semantics import Message, PairedFixture, TransitionBounds, TransitionProfile


def message(nonce: int) -> Message:
    return Message("source", "destination", "bridge", "receiver", nonce, f"commit-{nonce}")


class BoundedPairedExplorerTests(unittest.TestCase):
    def test_finds_reordering_counterexample_with_action_evidence(self) -> None:
        result = BoundedPairedExplorer([message(1), message(2)]).search(
            PairedFixture(bounds=TransitionBounds(4, 4, 2)),
            lambda state: (
                bool(state.delivered)
                and state.delivered[0].nonce == 2
                and any(pending.nonce == 1 for pending in state.pending)
            ),
        )
        self.assertEqual(result.status, SearchStatus.SAT)
        self.assertTrue(result.complete)
        self.assertEqual([action.action.value for action in result.witness], ["enqueue", "enqueue", "deliver"])
        self.assertEqual(result.witness[-1].message.nonce, 2)

    def test_reports_bounded_unsat_only_after_schedule_space_is_exhausted(self) -> None:
        result = BoundedPairedExplorer([message(1)]).search(
            PairedFixture(bounds=TransitionBounds(2, 2, 1)),
            lambda _state: False,
        )
        self.assertEqual(result.status, SearchStatus.BOUNDED_UNSAT)
        self.assertTrue(result.complete)
        self.assertEqual(result.reason, "finite_schedule_space_exhausted")
        self.assertGreater(result.explored_states, 0)

    def test_operational_state_limit_never_claims_unsat(self) -> None:
        result = BoundedPairedExplorer([message(1)], max_states=1).search(
            PairedFixture(bounds=TransitionBounds(2, 2, 1)),
            lambda _state: False,
        )
        self.assertEqual(result.status, SearchStatus.UNKNOWN)
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "state_limit_exhausted")

    def test_duplicate_candidate_message_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique identities"):
            BoundedPairedExplorer([message(1), message(1)])

    def test_duplicate_schedule_is_explored_only_when_profile_allows_it(self) -> None:
        result = BoundedPairedExplorer([message(1)]).search(
            PairedFixture(
                bounds=TransitionBounds(2, 2, 2),
                profile=TransitionProfile(allow_duplicate_enqueue=True),
            ),
            lambda state: len(state.pending) == 2,
        )
        self.assertEqual(result.status, SearchStatus.SAT)
        self.assertEqual([action.action.value for action in result.witness], ["enqueue", "enqueue"])

    def test_timeout_and_cancellation_are_not_proofs(self) -> None:
        now = [0.0]

        def clock() -> float:
            now[0] += 0.5
            return now[0]

        timeout = BoundedPairedExplorer([message(1)]).search(
            PairedFixture(bounds=TransitionBounds(2, 2, 1)),
            lambda _state: False,
            control=SearchControl(query_timeout_seconds=0.25, campaign_deadline_seconds=1.0),
            clock=clock,
        )
        self.assertEqual(timeout.status.value, "timeout")
        self.assertFalse(timeout.complete)
        self.assertEqual(timeout.reason, "query_timeout")

        cancelled = BoundedPairedExplorer([message(1)]).search(
            PairedFixture(bounds=TransitionBounds(2, 2, 1)),
            lambda _state: False,
            cancelled=lambda: True,
        )
        self.assertEqual(cancelled.status.value, "unknown")
        self.assertFalse(cancelled.complete)
        self.assertEqual(cancelled.reason, "cancelled")

    def test_control_rejects_inverted_deadlines(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            SearchControl(query_timeout_seconds=2.0, campaign_deadline_seconds=1.0)

    def test_prior_campaign_work_consumes_shared_deadline(self) -> None:
        result = BoundedPairedExplorer([message(1)]).search(
            PairedFixture(bounds=TransitionBounds(2, 2, 1)),
            lambda _state: False,
            control=SearchControl(
                query_timeout_seconds=10.0,
                campaign_deadline_seconds=10.0,
                campaign_elapsed_seconds=10.0,
            ),
        )
        self.assertEqual(result.status, SearchStatus.TIMEOUT)
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "campaign_deadline")

    def test_predicate_error_is_not_reported_as_bounded_unsat(self) -> None:
        result = BoundedPairedExplorer([message(1)]).search(
            PairedFixture(),
            lambda _state: (_ for _ in ()).throw(RuntimeError("property unavailable")),
        )
        self.assertEqual(result.status, SearchStatus.CRASH)
        self.assertFalse(result.complete)
        self.assertIn("predicate_error:RuntimeError", result.reason or "")

    def test_reorg_profile_is_part_of_explored_transition_space(self) -> None:
        result = BoundedPairedExplorer([message(1)]).search(
            PairedFixture(
                bounds=TransitionBounds(3, 2, 1),
                profile=TransitionProfile(allow_pre_finality_reorg=True, finality_depth=1),
            ),
            lambda state: not state.source.committed_messages and state.transaction_count == 2,
        )
        self.assertEqual(result.status, SearchStatus.SAT)
        self.assertEqual([action.action.value for action in result.witness], ["enqueue", "reorg"])


if __name__ == "__main__":
    unittest.main()
