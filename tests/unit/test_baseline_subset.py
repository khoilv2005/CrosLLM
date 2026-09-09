from __future__ import annotations

import unittest

from crossllm.baselines import select_balanced_subset


class BaselineSubsetTests(unittest.TestCase):
    def records(self):
        return [
            {
                "instance_id": f"i{index}",
                "lineage_id": f"l{index % 4}",
                "family": f"f{index % 3}",
                "ground_truth": "positive" if index % 2 == 0 else "negative",
                "outcome_should_not_be_read": index,
            }
            for index in range(24)
        ]

    def test_selection_is_seeded_balanced_and_outcome_blind(self) -> None:
        first = select_balanced_subset(self.records(), target_size=12, seed=7, min_lineages=4, min_families=3)
        second = select_balanced_subset(self.records(), target_size=12, seed=7, min_lineages=4, min_families=3)
        self.assertEqual(first, second)
        self.assertEqual(len(first.record_ids), 12)
        self.assertEqual(len(first.counts["lineage"]), 4)
        self.assertEqual(len(first.counts["family"]), 3)
        self.assertEqual(set(first.counts["ground_truth"]), {"positive", "negative"})
        self.assertEqual(len(first.selection_hash), 64)

    def test_missing_strata_and_impossible_coverage_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "identity/strata"):
            select_balanced_subset([{"instance_id": "i"}], target_size=2, seed=1, min_lineages=1, min_families=1)
        with self.assertRaisesRegex(ValueError, "cannot satisfy"):
            select_balanced_subset(self.records(), target_size=1, seed=1, min_lineages=2, min_families=1)

    def test_labels_population_hash_and_operational_coverage_are_recorded(self) -> None:
        records = [
            {
                **row,
                "cohort": "sealed" if row["ground_truth"] == "positive" else "negative",
                "supported_methods": ["slither", "ityfuzz"] if int(row["instance_id"][1:]) % 3 else ["slither"],
            }
            for row in self.records()
        ]
        selection = select_balanced_subset(
            records,
            target_size=12,
            seed=7,
            min_lineages=4,
            min_families=3,
            truth_field="cohort",
            positive_label="sealed",
            negative_label="negative",
            support_field="supported_methods",
            required_methods=("slither", "ityfuzz"),
        )
        self.assertEqual(len(selection.population_hash), 64)
        self.assertFalse(selection.operational_coverage["outcomes_used"])
        self.assertEqual(selection.operational_coverage["denominator"], 12)
        self.assertLess(selection.operational_coverage["common_supported_count"], 12)
        self.assertEqual(selection.as_dict()["criteria"]["positive_label"], "sealed")

    def test_support_methods_require_a_support_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "support_field"):
            select_balanced_subset(
                self.records(), target_size=12, seed=7, min_lineages=4,
                min_families=3, required_methods=("slither",),
            )

    def test_pre_outcome_balance_fields_are_reported(self) -> None:
        selection = select_balanced_subset(
            [
                {**row, "architecture": "a" if int(row["instance_id"][1:]) % 2 else "b"}
                for row in self.records()
            ],
            target_size=12,
            seed=7,
            min_lineages=4,
            min_families=3,
            balance_fields=("architecture",),
        )
        self.assertEqual(set(selection.counts["architecture"]), {"a", "b"})
        self.assertEqual(selection.criteria["balance_fields"], ["architecture"])


if __name__ == "__main__":
    unittest.main()
