from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.validate_toolchain_lock import _parse_requirements, validate


ROOT = Path(__file__).resolve().parents[2]


class ToolchainLockTests(unittest.TestCase):
    def test_repository_lock_is_hash_pinned_and_platform_aware(self) -> None:
        entries, errors = _parse_requirements(ROOT / "requirements.lock")
        self.assertEqual(errors, [])
        self.assertGreaterEqual(len(entries), 6)
        self.assertTrue(all(entry["hashes"] for entry in entries))
        z3_entries = [entry for entry in entries if entry["name"] == "z3-solver"]
        self.assertEqual({entry["version"] for entry in z3_entries}, {"5.1.0.0", "4.15.4.0"})

    def test_repository_toolchain_lock_passes_without_promoting_status(self) -> None:
        result, errors = validate(ROOT)
        self.assertEqual(errors, [])
        self.assertEqual(result["status"], "development_probe")
        self.assertTrue(result["ci_hash_install"])
        self.assertFalse(result["admission_eligible"])

    def test_missing_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "requirements.lock").write_text("demo==1.0\n", encoding="utf-8")
            entries, errors = _parse_requirements(root / "requirements.lock")
            self.assertEqual(len(entries), 1)
            self.assertIn("missing sha256 hash", errors[0])


if __name__ == "__main__":
    unittest.main()
