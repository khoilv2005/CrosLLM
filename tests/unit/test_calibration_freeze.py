from __future__ import annotations

import unittest

from crossllm.calibration import (
    CalibrationObservation,
    CalibrationSetting,
    SelectionRule,
    freeze_development_selection,
    select_development_setting,
)


class CalibrationFreezeTests(unittest.TestCase):
    def selection(self):
        settings = [
            CalibrationSetting("low", "low", 0.5, 100, 0.1),
            CalibrationSetting("high", "high", 0.5, 100, 0.2),
        ]
        observations = [
            CalibrationObservation("low", "development", 0.8, 0.01, 10),
            CalibrationObservation("high", "development", 0.8, 0.01, 10),
        ]
        return select_development_setting(settings, observations, rule=SelectionRule())

    def hashes(self) -> dict[str, str]:
        return {name: f"hash-{name}" for name in (
            "protocol_hash", "prompt_hash", "primitives_hash", "mutation_policy_hash",
            "harness_policy_hash", "runtime_policy_hash", "analysis_code_hash",
        )}

    def test_freeze_is_hash_addressed_and_development_only(self) -> None:
        first = freeze_development_selection(self.selection(), hashes=self.hashes())
        second = freeze_development_selection(self.selection(), hashes=self.hashes())
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual(first.selection.setting_id, "low")
        self.assertEqual(len(first.freeze_hash), 64)

    def test_missing_hash_or_evaluation_observation_is_rejected(self) -> None:
        hashes = self.hashes()
        hashes.pop("analysis_code_hash")
        with self.assertRaisesRegex(ValueError, "missing hashes"):
            freeze_development_selection(self.selection(), hashes=hashes)
        with self.assertRaisesRegex(ValueError, "evaluation observations"):
            freeze_development_selection(self.selection(), hashes=self.hashes(), evaluation_observation_ids=("eval-1",))


if __name__ == "__main__":
    unittest.main()
