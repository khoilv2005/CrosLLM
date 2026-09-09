from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from crossllm.cli import main


class CLIEvaluationLaunchTests(unittest.TestCase):
    def test_launch_check_is_side_effect_free_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {}
            for name in ("protocol", "models", "toolchain", "plan", "evidence"):
                path = root / f"{name}.json"
                path.write_text("{}", encoding="utf-8")
                paths[name] = path
            report_path = root / "launch-report.json"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main([
                    "evaluation-launch-check",
                    "--protocol", str(paths["protocol"]),
                    "--models", str(paths["models"]),
                    "--toolchain", str(paths["toolchain"]),
                    "--plan", str(paths["plan"]),
                    "--evidence", str(paths["evidence"]),
                    "--report-out", str(report_path),
                ])
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 3)
            self.assertFalse(payload["launch"]["allowed"])
            self.assertFalse(payload["launch"]["provider_calls_started"])
            self.assertEqual(payload["readiness"]["mode"], "evaluation")
            self.assertTrue(report_path.exists())


if __name__ == "__main__":
    unittest.main()
