from __future__ import annotations

import unittest

from crossllm.analysis import exact_two_sided_sign_test, holm_adjust, paired_lineage_bootstrap


class AnalysisInferenceTests(unittest.TestCase):
    def test_exact_sign_test_reports_ties_and_no_zero_effect_inference(self) -> None:
        result = exact_two_sided_sign_test([1.0, 0.0, -1.0])
        self.assertEqual((result.wins, result.losses, result.ties, result.effective_n), (1, 1, 1, 2))
        self.assertEqual(result.p_value, 1.0)
        zero = exact_two_sided_sign_test([0.0, 0.0])
        self.assertIsNone(zero.p_value)
        self.assertEqual(zero.effective_n, 0)

    def test_holm_adjustment_is_deterministic_and_preserves_keys(self) -> None:
        adjusted = holm_adjust({"b": 0.03, "a": 0.01, "c": 0.2})
        self.assertEqual(adjusted, {"a": 0.03, "b": 0.06, "c": 0.2})

    def test_bootstrap_resamples_whole_lineages_and_is_seeded(self) -> None:
        effects = {"l2": 1.0, "l1": 0.0, "l3": 0.5}
        first = paired_lineage_bootstrap(effects, draws=101, seed=42)
        second = paired_lineage_bootstrap(effects, draws=101, seed=42)
        self.assertEqual(first, second)
        self.assertEqual(first.lineage_count, 3)
        self.assertAlmostEqual(first.estimate, 0.5)
        self.assertLessEqual(first.ci_low, first.estimate)
        self.assertGreaterEqual(first.ci_high, first.estimate)

    def test_empty_bootstrap_has_explicit_missing_summary(self) -> None:
        result = paired_lineage_bootstrap({}, draws=10, seed=1)
        self.assertIsNone(result.estimate)
        self.assertIsNone(result.ci_low)
        self.assertEqual(result.lineage_count, 0)


if __name__ == "__main__":
    unittest.main()
