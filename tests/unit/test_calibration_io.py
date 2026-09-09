from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crossllm.calibration import (
    CalibrationObservation,
    CalibrationSetting,
    SelectionRule,
    load_selection_decision,
    select_development_setting,
)


class CalibrationIOTests(unittest.TestCase):
    def test_selection_artifact_round_trips_and_hash_tampering_is_rejected(self) -> None:
        settings = [
            CalibrationSetting("low", "low", 0.5, 100, 0.1),
            CalibrationSetting("high", "high", 0.5, 100, 0.2),
        ]
        decision = select_development_setting(settings, [
            CalibrationObservation("low", "development", 0.8, 0.01, 10),
            CalibrationObservation("high", "development", 0.8, 0.01, 10),
        ], rule=SelectionRule())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selection.json"
            path.write_text(json.dumps(decision.as_dict()), encoding="utf-8")
            self.assertEqual(load_selection_decision(path).selection_hash, decision.selection_hash)
            payload = decision.as_dict()
            payload["selection_hash"] = "bad"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                load_selection_decision(path)


if __name__ == "__main__":
    unittest.main()
