from __future__ import annotations

import unittest

from crossllm.calibration import (
    BudgetInputs,
    CalibrationObservation,
    CalibrationSetting,
    PrecisionSimulationConfig,
    SelectionRule,
    build_compact_calibration_menu,
    estimate_budget,
    select_common_replicates,
    select_development_setting,
    simulate_hierarchical_precision,
)


class CalibrationTests(unittest.TestCase):
    def test_compact_menu_is_exact_two_by_two_and_outcome_independent(self) -> None:
        menu = build_compact_calibration_menu(
            reasoning_levels=("low", "high"),
            starting_temperature=0.7,
            temperature_delta=0.2,
            output_cap=8192,
            estimated_cost_usd={("low", 0.5): 1.0, ("low", 0.9): 1.1, ("high", 0.5): 2.0, ("high", 0.9): 2.1},
        )
        self.assertEqual(len(menu), 4)
        self.assertEqual({setting.reasoning_level for setting in menu}, {"low", "high"})
        self.assertEqual({setting.temperature for setting in menu}, {0.5, 0.9})
        self.assertEqual([setting.setting_id for setting in menu], ["cal-low-t0.5", "cal-low-t0.9", "cal-high-t0.5", "cal-high-t0.9"])
        with self.assertRaisesRegex(ValueError, "exactly two"):
            build_compact_calibration_menu(
                reasoning_levels=("low", "high", "max"), starting_temperature=0.7,
                temperature_delta=0.2, output_cap=8192,
            )

    def settings(self):
        return [
            CalibrationSetting("cheap", "low", 0.2, 16384, 1.0),
            CalibrationSetting("strong", "high", 0.2, 32768, 2.0),
            CalibrationSetting("unstable", "high", 0.8, 32768, 0.5),
        ]

    def test_selection_is_development_only_and_prefers_cheapest_within_recall_tolerance(self) -> None:
        observations = [
            CalibrationObservation("cheap", "development", 0.79, 0.01, 10),
            CalibrationObservation("strong", "development", 0.80, 0.02, 10),
            CalibrationObservation("unstable", "development", 0.80, 0.10, 10),
        ]
        decision = select_development_setting(self.settings(), observations, rule=SelectionRule(recall_tolerance=0.02))
        self.assertEqual(decision.setting_id, "cheap")
        self.assertEqual(decision.eligible_setting_ids, ("cheap", "strong"))
        self.assertEqual(len(decision.selection_hash), 64)
        with self.assertRaisesRegex(ValueError, "evaluation observations"):
            select_development_setting(self.settings(), observations + [CalibrationObservation("cheap", "evaluation", 1.0, 0.0, 1)])

    def test_budget_includes_retries_baselines_calibration_and_adjudication(self) -> None:
        result = estimate_budget(BudgetInputs(
            campaign_count=10,
            provider_calls_per_campaign=8,
            expected_input_tokens=100,
            expected_generated_tokens=20,
            expected_retries_per_call=0.5,
            solver_core_seconds_per_campaign=3600,
            baseline_campaign_count=2,
            calibration_campaign_count=3,
            adjudication_case_count=5,
            adjudication_seconds_per_case=720,
            input_cost_per_token=0.001,
            generated_cost_per_token=0.002,
        ))
        self.assertEqual(result.total_campaigns, 15)
        self.assertEqual(result.provider_calls, 180.0)
        self.assertEqual(result.input_tokens, 18000)
        self.assertEqual(result.generated_tokens, 3600)
        self.assertEqual(result.solver_core_hours, 15.0)
        self.assertEqual(result.adjudication_hours, 1.0)
        self.assertEqual(result.estimated_provider_cost_usd, 25.2)

    def test_paired_precision_simulation_is_seeded_and_tracks_unequal_lineages(self) -> None:
        config = PrecisionSimulationConfig({"l1": 1, "l2": 3}, campaigns_per_instance=2, draws=101, seed=4)
        probabilities = {
            "l1": (0.5, 0.2, 0.1, 0.2),
            "l2": (0.4, 0.3, 0.1, 0.2),
        }
        first = simulate_hierarchical_precision(config, joint_probabilities=probabilities)
        second = simulate_hierarchical_precision(config, joint_probabilities=probabilities)
        self.assertEqual(first, second)
        self.assertEqual(first.draws, 101)
        self.assertGreaterEqual(first.recall_mcse, 0.0)
        self.assertGreaterEqual(first.difference_mcse, 0.0)
        self.assertGreaterEqual(first.between_lineage_recall_sd, 0.0)
        self.assertGreaterEqual(first.between_lineage_difference_sd, 0.0)
        self.assertGreaterEqual(first.conditional_recall_sd, 0.0)
        self.assertGreaterEqual(first.conditional_difference_sd, 0.0)
        self.assertEqual(first.conditional_recall_mcse, first.recall_mcse)
        self.assertEqual(first.conditional_difference_mcse, first.difference_mcse)

    def test_invalid_joint_probabilities_are_rejected(self) -> None:
        config = PrecisionSimulationConfig({"l1": 1}, campaigns_per_instance=1, draws=2)
        with self.assertRaisesRegex(ValueError, "invalid joint"):
            simulate_hierarchical_precision(config, joint_probabilities={"l1": (0.5, 0.5, 0.5, 0.5)})

    def test_single_lineage_reports_zero_between_lineage_spread(self) -> None:
        config = PrecisionSimulationConfig({"l1": 2}, campaigns_per_instance=2, draws=5)
        result = simulate_hierarchical_precision(
            config,
            joint_probabilities={"l1": (0.5, 0.2, 0.1, 0.2)},
        )
        self.assertEqual(result.between_lineage_recall_sd, 0.0)
        self.assertEqual(result.between_lineage_difference_sd, 0.0)

    def test_common_replicate_selection_uses_smallest_candidate_meeting_both_targets(self) -> None:
        config = PrecisionSimulationConfig(
            {"l1": 2, "l2": 2}, campaigns_per_instance=1, draws=101, seed=9,
            target_recall_mcse=1.0, target_difference_mcse=1.0,
        )
        selection = select_common_replicates(
            config,
            joint_probabilities={
                "l1": (0.5, 0.2, 0.1, 0.2),
                "l2": (0.4, 0.3, 0.1, 0.2),
            },
        )
        self.assertEqual(selection.candidate_replicates, (5, 10, 20))
        self.assertEqual(selection.selected_replicates, 5)
        self.assertEqual([row.campaigns_per_instance for row in selection.candidates], [5, 10, 20])
        self.assertEqual(selection.reason, "smallest_candidate_meeting_both_mcse_targets")

    def test_common_replicate_selection_reports_precision_limitation(self) -> None:
        config = PrecisionSimulationConfig(
            {"l1": 1}, campaigns_per_instance=1, draws=11, seed=2,
            target_recall_mcse=0.0, target_difference_mcse=0.0,
        )
        selection = select_common_replicates(
            config,
            joint_probabilities={"l1": (0.5, 0.2, 0.1, 0.2)},
            candidates=(5, 10),
        )
        self.assertIsNone(selection.selected_replicates)
        self.assertEqual(selection.reason, "no_candidate_meets_mcse_targets")

    def test_duplicate_setting_observations_are_rejected(self) -> None:
        observations = [
            CalibrationObservation("cheap", "development", 0.8, 0.0, 1),
            CalibrationObservation("cheap", "development", 0.8, 0.0, 1),
        ]
        with self.assertRaisesRegex(ValueError, "one development observation"):
            select_development_setting(self.settings(), observations)


if __name__ == "__main__":
    unittest.main()
