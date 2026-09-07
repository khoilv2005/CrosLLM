from __future__ import annotations

import unittest

from crossllm.semantics import Message, PairedFixture


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
        with self.assertRaisesRegex(ValueError, "duplicate pending"):
            fixture.enqueue(self.message(1))

    def test_domain_mismatch_cannot_enter_channel(self) -> None:
        fixture = PairedFixture()
        bad = Message("other", "destination", "bridge", "receiver", 1, "commit")
        with self.assertRaisesRegex(ValueError, "source domain mismatch"):
            fixture.enqueue(bad)


if __name__ == "__main__":
    unittest.main()
