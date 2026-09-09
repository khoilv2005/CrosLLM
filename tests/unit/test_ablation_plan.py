from __future__ import annotations

import unittest

from crossllm.methods import AblationPhase, AblationArm, AblationStudy, build_p0_ablation_plan


class AblationPlanTests(unittest.TestCase):
    def test_p0_plan_contains_five_primary_contrasts_and_late_gold_diagnostic(self) -> None:
        plan = build_p0_ablation_plan()
        self.assertEqual(len(plan.studies), 6)
        primary = [study for study in plan.studies if study.phase is AblationPhase.PRIMARY]
        diagnostic = [study for study in plan.studies if study.phase is AblationPhase.POST_PRIMARY_DIAGNOSTIC]
        self.assertEqual(len(primary), 5)
        self.assertEqual(len(diagnostic), 1)
        self.assertTrue(all(not study.gold_access for study in primary))
        self.assertTrue(diagnostic[0].gold_access)
        self.assertEqual(len(plan.plan_hash), 64)

    def test_ablation_rejects_changes_to_more_than_one_component(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly the declared"):
            AblationStudy(
                "bad", "proposer",
                AblationArm("left", {"proposer": "learned", "downstream": "fixed"}),
                AblationArm("right", {"proposer": "t0", "downstream": "changed"}),
            )

    def test_grounding_ablation_declares_shared_stored_pool(self) -> None:
        study = next(study for study in build_p0_ablation_plan().studies if study.study_id == "grounding-early-vs-deferred")
        self.assertIn("stored_proposal_pool", study.shared_inputs)
        self.assertEqual(study.left.settings["proposal_pool"], study.right.settings["proposal_pool"])


if __name__ == "__main__":
    unittest.main()
