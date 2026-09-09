from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from crossllm.cli import main


class CLICalibrationTests(unittest.TestCase):
    def test_select_and_budget_commands_write_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "settings.json"
            observations = root / "observations.json"
            selection = root / "nested" / "selection.json"
            budget = root / "nested" / "budget.json"
            settings.write_text(json.dumps([{
                "setting_id": "low", "reasoning_level": "low", "temperature": 0.5,
                "output_cap": 100, "estimated_cost_usd": 0.1,
            }]), encoding="utf-8")
            observations.write_text(json.dumps([{
                "setting_id": "low", "split": "development", "recall": 0.8,
                "truncation_rate": 0.01, "calls": 10,
            }]), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["calibrate-select", "--settings", str(settings), "--observations", str(observations), "--out", str(selection)]), 0)
            inputs = root / "inputs.json"
            inputs.write_text(json.dumps({
                "campaign_count": 1, "provider_calls_per_campaign": 2,
                "expected_input_tokens": 10, "expected_generated_tokens": 5,
            }), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["budget-estimate", "--inputs", str(inputs), "--out", str(budget)]), 0)
            self.assertEqual(json.loads(selection.read_text(encoding="utf-8"))["setting_id"], "low")
            self.assertEqual(json.loads(budget.read_text(encoding="utf-8"))["total_campaigns"], 1)

            precision_config = root / "precision.json"
            probabilities = root / "probabilities.json"
            replicate_selection = root / "nested" / "replicate-selection.json"
            precision_config.write_text(json.dumps({
                "instances_per_lineage": {"l1": 2, "l2": 2},
                "campaigns_per_instance": 1,
                "draws": 101,
                "seed": 9,
                "target_recall_mcse": 1.0,
                "target_difference_mcse": 1.0,
            }), encoding="utf-8")
            probabilities.write_text(json.dumps({
                "l1": [0.5, 0.2, 0.1, 0.2],
                "l2": [0.4, 0.3, 0.1, 0.2],
            }), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([
                    "calibrate-simulate", "--config", str(precision_config),
                    "--probabilities", str(probabilities), "--replicate-candidates",
                    "5", "10", "20", "--out", str(replicate_selection),
                ]), 0)
            self.assertEqual(
                json.loads(replicate_selection.read_text(encoding="utf-8"))["selected_replicates"],
                5,
            )


if __name__ == "__main__":
    unittest.main()
