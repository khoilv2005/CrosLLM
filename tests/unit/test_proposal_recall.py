from __future__ import annotations

import unittest

from crossllm.analysis import (
    BatchAvailability,
    EndToEndObservation,
    ProposalBatch,
    end_to_end_budget_recall,
    proposal_prefix_recall,
)


class ProposalRecallTests(unittest.TestCase):
    def test_prefix_recall_uses_stored_order_and_keeps_missing_out(self) -> None:
        result = proposal_prefix_recall(
            [
                ProposalBatch("b1", "i1", ("p-no", "p-hit"), ("p-hit",)),
                ProposalBatch("b2", "i2", ("p-hit",), ("p-hit",)),
                ProposalBatch("b3", "i3", (), (), BatchAvailability.MISSING, "archive_not_found"),
            ],
            prefixes=(1, 2),
        )
        self.assertAlmostEqual(result.metrics[1].value, 0.5)
        self.assertAlmostEqual(result.metrics[2].value, 1.0)
        self.assertEqual(result.metrics[1].total, 3)
        self.assertEqual(result.metrics[1].missing, 1)
        self.assertEqual(result.as_dict()["endpoint_separation"], "stored_ordered_proposals_only")

    def test_end_to_end_endpoint_is_separate_and_tracks_budget_observations(self) -> None:
        result = end_to_end_budget_recall(
            [
                EndToEndObservation("o1", "i1", 1, True),
                EndToEndObservation("o2", "i2", 1, False),
                EndToEndObservation("o3", "i3", 2, True),
                EndToEndObservation("o4", "i4", 2, None, BatchAvailability.MISSING, "timeout"),
            ],
            budgets=(1, 2),
        )
        self.assertEqual(result.metrics[1].value, 0.5)
        self.assertEqual(result.metrics[2].value, 1.0)
        self.assertEqual(result.metrics[2].missing, 1)
        self.assertEqual(result.as_dict()["endpoint_separation"], "scheduled_campaign_outcomes_only")

    def test_duplicate_batch_ids_and_invalid_available_rows_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "available proposal batch"):
            ProposalBatch("b", "i", ("p",), ())
        batch = ProposalBatch("b", "i", ("p",), ("p",))
        with self.assertRaisesRegex(ValueError, "proposal batch IDs"):
            proposal_prefix_recall([batch, batch])


if __name__ == "__main__":
    unittest.main()
