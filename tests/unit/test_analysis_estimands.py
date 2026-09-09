from __future__ import annotations

import unittest

from crossllm.analysis import CampaignOutcome, OutcomeAvailability, analyze_outcomes


class AnalysisEstimandTests(unittest.TestCase):
    def rows(self) -> list[CampaignOutcome]:
        return [
            CampaignOutcome("x-l1-i1-r1", "i1", "l1", "X", 1, "positive", detected=True, useful_proposal=True, native_witness=True, independent_replay=True, claim_time_seconds=2, witness_time_seconds=1, horizon_seconds=10),
            CampaignOutcome("x-l1-i1-r2", "i1", "l1", "X", 2, "positive", detected=False, useful_proposal=False, native_witness=False, independent_replay=False, claim_time_seconds=None, witness_time_seconds=None, horizon_seconds=10, availability=OutcomeAvailability.TIMEOUT),
            CampaignOutcome("p-l1-i1-r1", "i1", "l1", "P", 1, "positive", detected=False, useful_proposal=False, native_witness=False, independent_replay=False, claim_time_seconds=None, witness_time_seconds=None, horizon_seconds=10),
            CampaignOutcome("x-l2-i2-r1", "i2", "l2", "X", 1, "positive", detected=True, useful_proposal=True, native_witness=True, independent_replay=True, claim_time_seconds=3, witness_time_seconds=2, horizon_seconds=10),
            CampaignOutcome("x-l2-i3-r1", "i3", "l2", "X", 1, "positive", detected=True, useful_proposal=True, native_witness=False, independent_replay=None, claim_time_seconds=4, witness_time_seconds=None, horizon_seconds=10),
            CampaignOutcome("p-l2-i2-r1", "i2", "l2", "P", 1, "positive", detected=False, useful_proposal=False, native_witness=False, independent_replay=False, claim_time_seconds=None, witness_time_seconds=None, horizon_seconds=10),
            CampaignOutcome("p-l2-i3-r1", "i3", "l2", "P", 1, "positive", detected=False, useful_proposal=False, native_witness=False, independent_replay=False, claim_time_seconds=None, witness_time_seconds=None, horizon_seconds=10),
            CampaignOutcome("x-l1-neg-r1", "n1", "l1", "X", 1, "negative", claim_emitted=True, correct_claim=False),
        ]

    def test_recall_is_lineage_balanced_and_paired_effects_precede_aggregation(self) -> None:
        report = analyze_outcomes(self.rows(), compare_methods=("X", "P"))
        self.assertAlmostEqual(report.recall["X"].value, 0.75)
        self.assertEqual(report.recall["X"].known, 4)
        self.assertEqual(report.paired_effects["X-minus-P"], (0.5, 1.0))

    def test_false_alert_and_precision_keep_no_claims_as_na(self) -> None:
        report = analyze_outcomes(self.rows())
        self.assertEqual(report.false_alert_rate["X"].value, 1.0)
        self.assertEqual(report.false_discovery_proportion["X"].value, 1.0)
        self.assertIsNone(report.false_discovery_proportion["P"].value)
        self.assertEqual(report.false_discovery_proportion["P"].note, "precision_NA_no_claims")

    def test_missingness_is_explicit_and_time_is_censored_at_horizon(self) -> None:
        rows = [
            CampaignOutcome("a", "i", "l", "X", 1, "positive", detected=True, claim_time_seconds=None, horizon_seconds=5),
            CampaignOutcome("b", "j", "l", "X", 1, "positive", detected=None, claim_time_seconds=9, horizon_seconds=5, availability=OutcomeAvailability.PROVIDER_FAILURE),
        ]
        report = analyze_outcomes(rows)
        self.assertEqual(report.recall["X"].known, 1)
        self.assertEqual(report.recall["X"].missing, 1)
        self.assertEqual(report.claim_time["X"].value, 5.0)
        self.assertEqual(report.claim_time["X"].missing, 1)
        details = report.time_details["X"]["claim_time"]
        self.assertEqual(details.restricted.value, 5.0)
        self.assertEqual(details.availability_conditioned.value, 5.0)
        self.assertEqual(details.intention_to_run.value, 0.5)
        self.assertEqual(details.kaplan_meier[-1]["survival"], 1.0)
        self.assertEqual(report.stage_denominators["X"]["detected"]["missing"], 1)
        self.assertEqual(report.stage_denominators["X"]["availability"]["provider_failure"], 1)

    def test_duplicate_campaigns_are_rejected(self) -> None:
        row = self.rows()[0]
        with self.assertRaisesRegex(ValueError, "duplicate campaign_id"):
            analyze_outcomes([row, row])

    def test_reordering_rows_does_not_change_report(self) -> None:
        rows = self.rows()
        first = analyze_outcomes(rows, compare_methods=("X", "P")).as_dict()
        second = analyze_outcomes(list(reversed(rows)), compare_methods=("X", "P")).as_dict()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
