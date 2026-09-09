from __future__ import annotations

import unittest

from crossllm.semantics import Message, PairedFixture, TransitionBounds, TransitionProfile


class PairedFixtureTests(unittest.TestCase):
    def message(self, nonce: int = 1) -> Message:
        return Message("source", "destination", "bridge", "receiver", nonce, f"commit-{nonce}")

    def test_enqueue_deliver_and_snapshot_restore(self) -> None:
        fixture = PairedFixture()
        initial = fixture.snapshot()
        fixture.enqueue(self.message())
        fixture.deliver()
        self.assertEqual(fixture.state.destination.storage["received:1"], "commit-1")
        fixture.restore(initial)
        self.assertEqual(fixture.state.pending, [])
        self.assertEqual(fixture.state.destination.storage, {})

    def test_reordering_is_explicit_and_duplicate_identity_is_rejected(self) -> None:
        fixture = PairedFixture()
        fixture.enqueue(self.message(1))
        fixture.enqueue(self.message(2))
        self.assertEqual(fixture.deliver(index=1).nonce, 2)
        with self.assertRaisesRegex(ValueError, "duplicate message"):
            fixture.enqueue(self.message(1))

    def test_duplicate_enqueue_requires_an_explicit_adversarial_profile(self) -> None:
        fixture = PairedFixture(
            bounds=TransitionBounds(3, 3, 2),
            profile=TransitionProfile(allow_duplicate_enqueue=True),
        )
        fixture.enqueue(self.message(1))
        fixture.enqueue(self.message(1))
        self.assertEqual([message.nonce for message in fixture.state.pending], [1, 1])

    def test_domain_mismatch_cannot_enter_channel(self) -> None:
        fixture = PairedFixture()
        bad = Message("other", "destination", "bridge", "receiver", 1, "commit")
        with self.assertRaisesRegex(ValueError, "source domain mismatch"):
            fixture.enqueue(bad)

    def test_intent_identifier_is_part_of_message_identity(self) -> None:
        first = Message("source", "destination", "bridge", "receiver", 1, "commit", intent_id="intent-a")
        second = Message("source", "destination", "bridge", "receiver", 1, "commit", intent_id="intent-b")
        self.assertNotEqual(first.identity(), second.identity())
        fixture = PairedFixture(bounds=TransitionBounds(2, 2, 2))
        fixture.enqueue(first)
        fixture.enqueue(second)
        self.assertEqual([item.intent_id for item in fixture.state.pending], ["intent-a", "intent-b"])
        with self.assertRaisesRegex(ValueError, "intent_id"):
            Message("source", "destination", "bridge", "receiver", 2, "commit-2", intent_id="")

    def test_bounds_and_action_log_are_explicit(self) -> None:
        fixture = PairedFixture(bounds=TransitionBounds(2, 2, 1))
        fixture.enqueue(self.message())
        fixture.deliver()
        self.assertEqual(fixture.state.transaction_count, 2)
        self.assertEqual(fixture.state.channel_transition_count, 2)
        self.assertEqual([event.action.value for event in fixture.state.action_log], ["enqueue", "deliver"])
        with self.assertRaisesRegex(ValueError, "transaction bound exhausted"):
            fixture.enqueue(self.message(2))

    def test_pending_bound_and_observer_are_separate_from_chain_storage(self) -> None:
        fixture = PairedFixture(bounds=TransitionBounds(6, 12, 1))
        fixture.observe("monitor:last_nonce", 0)
        fixture.enqueue(self.message())
        with self.assertRaisesRegex(ValueError, "pending channel bound exhausted"):
            fixture.enqueue(self.message(2))
        self.assertEqual(fixture.state.observer_state, {"monitor:last_nonce": 0})
        self.assertEqual(fixture.state.source.storage, {})
        self.assertEqual(fixture.state.destination.storage, {})

    def test_invalid_bounds_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_pending"):
            TransitionBounds(max_pending=0)

    def test_message_encoding_is_checked_before_entering_a_search(self) -> None:
        with self.assertRaisesRegex(ValueError, "uint256"):
            Message("source", "destination", "bridge", "receiver", 2**256, "commit")
        with self.assertRaisesRegex(ValueError, "uint256"):
            Message("source", "destination", "bridge", "receiver", True, "commit")
        with self.assertRaisesRegex(ValueError, "non-empty"):
            Message("source", "destination", "bridge", "receiver", 1, "",)

    def test_profile_can_disable_reordering(self) -> None:
        fixture = PairedFixture(profile=TransitionProfile(allow_reordering=False))
        fixture.enqueue(self.message(1))
        fixture.enqueue(self.message(2))
        with self.assertRaisesRegex(ValueError, "reordering is disabled"):
            fixture.deliver(index=1)

    def test_reorg_is_bounded_by_finality_and_does_not_fake_channel_action(self) -> None:
        fixture = PairedFixture(
            bounds=TransitionBounds(4, 4, 2),
            profile=TransitionProfile(allow_pre_finality_reorg=True, finality_depth=1),
        )
        fixture.enqueue(self.message(1))
        fixture.enqueue(self.message(2))
        self.assertEqual(fixture.reorg_latest().nonce, 2)
        self.assertEqual([message.nonce for message in fixture.state.pending], [1])
        self.assertEqual(fixture.state.transaction_count, 3)
        self.assertEqual(fixture.state.channel_transition_count, 2)
        self.assertEqual(len(fixture.state.source.canonical_history), 1)

    def test_reorg_rejects_a_message_at_or_beyond_finality_depth(self) -> None:
        fixture = PairedFixture(
            bounds=TransitionBounds(5, 5, 3),
            profile=TransitionProfile(allow_pre_finality_reorg=True, finality_depth=1),
        )
        fixture.enqueue(self.message(1))
        fixture.enqueue(self.message(2))
        with self.assertRaisesRegex(ValueError, "finalized"):
            fixture.reorg(index=0)
        self.assertEqual(fixture.reorg(index=1).nonce, 2)
        self.assertEqual([message.nonce for message in fixture.state.pending], [1])

    def test_attestation_requires_fixed_authority(self) -> None:
        profile = TransitionProfile(
            require_attestation=True,
            authorized_emitters=("bridge",),
            authorized_attestors=("watcher",),
        )
        fixture = PairedFixture(profile=profile)
        with self.assertRaisesRegex(ValueError, "requires an attestation"):
            fixture.enqueue(self.message())
        with self.assertRaisesRegex(ValueError, "not authorized"):
            fixture.enqueue(Message("source", "destination", "bridge", "receiver", 2, "commit-2", "proof", "attacker"))
        fixture.enqueue(Message("source", "destination", "bridge", "receiver", 3, "commit-3", "proof", "watcher"))

    def test_reorg_requires_nonzero_finality_depth(self) -> None:
        with self.assertRaisesRegex(ValueError, "finality_depth"):
            TransitionProfile(allow_pre_finality_reorg=True)


if __name__ == "__main__":
    unittest.main()
