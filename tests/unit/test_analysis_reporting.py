from __future__ import annotations

import unittest

from crossllm.analysis import analyze_contrast_family, leave_one_lineage_out, zero_event_upper_bound


class AnalysisReportingTests(unittest.TestCase):
    def test_primary_and_secondary_families_are_analyzed_separately(self) -> None:
        primary = analyze_contrast_family(
            {f"primary-{index}": {"l1": 1.0, "l2": 1.0, "l3": 0.0} for index in range(5)},
            draws=25,
            seed=10,
        )
        secondary = analyze_contrast_family(
            {f"secondary-{index}": {"l1": 1.0, "l2": 0.0, "l3": 0.0} for index in range(6)},
            draws=25,
            seed=10,
        )
        self.assertEqual(len(primary), 5)
        self.assertEqual(len(secondary), 6)
        self.assertTrue(all(item.adjusted_p_value is not None for item in primary))
        self.assertEqual(primary[0].bootstrap.draws, 25)

    def test_zero_event_bound_and_leave_one_lineage_out_are_explicit(self) -> None:
        bound = zero_event_upper_bound(12)
        self.assertAlmostEqual(bound, 1 - 0.05 ** (1 / 12))
        self.assertEqual(leave_one_lineage_out({"l1": 0.0, "l2": 1.0}), {"l1": 1.0, "l2": 0.0})
        self.assertEqual(leave_one_lineage_out({"l1": 0.0}), {"l1": None})
        with self.assertRaisesRegex(ValueError, "positive"):
            zero_event_upper_bound(0)

    def test_all_zero_contrasts_have_no_sign_p_value(self) -> None:
        result = analyze_contrast_family({"contrast": {"l1": 0.0, "l2": 0.0}}, draws=5)
        self.assertIsNone(result[0].sign_test.p_value)
        self.assertIsNone(result[0].adjusted_p_value)


if __name__ == "__main__":
    unittest.main()
