from __future__ import annotations

import unittest

from crossllm.analysis import agreement_summary, stratified_sample


class AnalysisSamplingAgreementTests(unittest.TestCase):
    def records(self):
        return [
            {"id": "a1", "kind": "rejected"}, {"id": "a2", "kind": "rejected"}, {"id": "a3", "kind": "rejected"},
            {"id": "b1", "kind": "accepted"}, {"id": "b2", "kind": "accepted"},
        ]

    def test_stratified_sampling_is_seeded_and_reports_design_weights(self) -> None:
        kwargs = {
            "record_id": lambda row: row["id"],
            "stratum": lambda row: row["kind"],
            "sample_size_by_stratum": {"accepted": 1, "rejected": 2},
            "seed": 7,
        }
        first = stratified_sample(self.records(), **kwargs)
        second = stratified_sample(self.records(), **kwargs)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 3)
        self.assertEqual([(item.stratum, item.weight) for item in first], [("accepted", 2.0), ("rejected", 1.5), ("rejected", 1.5)])
        with self.assertRaisesRegex(ValueError, "exceeds population"):
            stratified_sample(self.records(), record_id=lambda row: row["id"], stratum=lambda row: row["kind"], sample_size_by_stratum={"accepted": 3}, seed=1)

    def test_agreement_keeps_missing_labels_and_confusion_matrix(self) -> None:
        summary = agreement_summary(
            {"f1": "confirmed", "f2": "rejected", "f3": "unresolved"},
            {"f1": "confirmed", "f2": "confirmed", "f4": "rejected"},
        )
        self.assertEqual((summary.matched, summary.missing_left, summary.missing_right), (2, 1, 1))
        self.assertEqual(summary.confusion["confirmed"]["confirmed"], 1)
        self.assertAlmostEqual(summary.observed_agreement, 0.5)
        self.assertIsNotNone(summary.kappa)

    def test_empty_agreement_is_not_perfect_agreement(self) -> None:
        summary = agreement_summary({}, {})
        self.assertIsNone(summary.observed_agreement)
        self.assertIsNone(summary.kappa)

    def test_cluster_bootstrap_keeps_lineage_members_together(self) -> None:
        left = {"a1": "confirmed", "a2": "rejected", "b1": "confirmed"}
        right = {"a1": "confirmed", "a2": "confirmed", "b1": "confirmed"}
        clusters = {"a1": "lineage-a", "a2": "lineage-a", "b1": "lineage-b"}
        first = agreement_summary(left, right, clusters=clusters, draws=101, seed=9)
        second = agreement_summary(left, right, clusters=clusters, draws=101, seed=9)
        self.assertEqual(first, second)
        self.assertIsNotNone(first.observed_agreement_ci)
        self.assertIsNotNone(first.kappa_ci)
        self.assertEqual(first.observed_agreement, 2 / 3)
        with self.assertRaisesRegex(ValueError, "cover exactly"):
            agreement_summary(left, right, clusters={"a1": "lineage-a"}, draws=3)


if __name__ == "__main__":
    unittest.main()
