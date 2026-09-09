from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.run_clean_worker_probe import build_and_probe, validate_report


ROOT = Path(__file__).resolve().parents[2]


class CleanWorkerProbeTests(unittest.TestCase):
    def test_checked_in_probe_is_valid(self) -> None:
        report_path = ROOT / "dataset" / "reports" / "clean_worker_probe.json"
        self.assertEqual(validate_report(ROOT, report_path), [])

    def test_report_hash_tampering_is_rejected(self) -> None:
        report = json.loads((ROOT / "dataset" / "reports" / "clean_worker_probe.json").read_text(encoding="utf-8"))
        report["status"] = "clean_worker_fail"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.json"
            path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.assertTrue(any("report_hash mismatch" in error for error in validate_report(ROOT, path)))


if __name__ == "__main__":
    unittest.main()
