from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from crossllm.runtime import CampaignPlanner


class CampaignPlannerTests(unittest.TestCase):
    def inputs(self):
        return {
            "mode": "development",
            "instances": [
                {"instance_id": "i1", "lineage_id": "l1"},
                {"instance_id": "i2", "lineage_id": "l2"},
            ],
            "methods": ["X", "P"],
            "backbones": [{"backbone": "Qwen", "model_tag": "qwen:test"}, {"backbone": "GLM", "model_tag": "glm:test"}],
            "replicates": 2,
            "seed": 17,
            "config": {"proposal_slots": 8, "k_tx": 6},
            "created_at": "2026-09-08T00:00:00Z",
        }

    def test_plan_is_deterministic_and_combinatorially_complete(self) -> None:
        planner = CampaignPlanner()
        first = planner.build(**self.inputs())
        second = planner.build(**self.inputs())
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual(len(first.campaigns), 2 * 2 * 2 * 2)
        self.assertEqual(len({row.campaign_id for row in first.campaigns}), len(first.campaigns))
        self.assertEqual([row.order_index for row in first.campaigns], list(range(16)))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaigns.plan.jsonl"
            first.write_jsonl(path)
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 16)
            metadata_path = Path(directory) / "campaigns.plan.json"
            first.write_json(metadata_path)
            self.assertEqual(len(json.loads(metadata_path.read_text(encoding="utf-8"))["campaigns"]), 16)

    def test_evaluation_requires_all_locks_and_replicates(self) -> None:
        planner = CampaignPlanner()
        inputs = self.inputs()
        inputs["mode"] = "evaluation"
        with self.assertRaisesRegex(ValueError, "requires protocol"):
            planner.build(**inputs)
        inputs.update(protocol_lock_hash="a" * 64, model_lock_hash="b" * 64, benchmark_manifest_hash="c" * 64)
        plan = planner.build(**inputs)
        self.assertEqual(plan.mode, "evaluation")
        for field in ("protocol_lock_hash", "model_lock_hash", "benchmark_manifest_hash"):
            invalid = dict(inputs)
            invalid[field] = "A" * 64
            with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
                planner.build(**invalid)
        inputs["replicates"] = None
        with self.assertRaisesRegex(ValueError, "replicates"):
            planner.build(**inputs)

    def test_duplicate_inputs_and_empty_methods_are_rejected(self) -> None:
        planner = CampaignPlanner()
        inputs = self.inputs()
        inputs["instances"] = [{"instance_id": "i1", "lineage_id": "l1"}, {"instance_id": "i1", "lineage_id": "l1"}]
        with self.assertRaisesRegex(ValueError, "unique"):
            planner.build(**inputs)
        inputs = self.inputs()
        inputs["methods"] = []
        with self.assertRaisesRegex(ValueError, "non-empty"):
            planner.build(**inputs)


if __name__ == "__main__":
    unittest.main()
