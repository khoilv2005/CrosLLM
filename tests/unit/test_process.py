from __future__ import annotations

import sys
from pathlib import Path
import unittest

from crossllm.replay.process import run_process


class ProcessControlTests(unittest.TestCase):
    def test_timeout_terminates_process_without_shell(self) -> None:
        outcome = run_process(
            (sys.executable, "-c", "import time; time.sleep(30)"),
            cwd=Path.cwd(),
            timeout_seconds=0.1,
        )
        self.assertEqual(outcome.reason, "timeout")
        self.assertIsNotNone(outcome.returncode)

    def test_callback_cancellation_is_preserved(self) -> None:
        calls = iter((False, True))
        outcome = run_process(
            (sys.executable, "-c", "import time; time.sleep(30)"),
            cwd=Path.cwd(),
            timeout_seconds=2.0,
            cancelled=lambda: next(calls, True),
        )
        self.assertEqual(outcome.reason, "cancelled")
        self.assertIsNotNone(outcome.returncode)


if __name__ == "__main__":
    unittest.main()
