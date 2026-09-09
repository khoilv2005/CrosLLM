from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import audit_source_cache
from dataset.tools import fetch_pinned_sources


class SourceCacheAuditTests(unittest.TestCase):
    def test_remote_normalization_only_ignores_transport_suffixes(self) -> None:
        self.assertEqual(
            fetch_pinned_sources.normalize_remote(
                "https://Example.invalid/Org/Demo.git/"
            ),
            "https://example.invalid/org/demo",
        )

    def test_audit_checks_origin_in_addition_to_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            cache = base / "cache"
            (root / "dataset" / "sources").mkdir(parents=True)
            (root / "dataset" / "artifacts").mkdir(parents=True)
            lineage = cache / "demo"
            lineage.mkdir(parents=True)

            def git(*args: str) -> str:
                result = subprocess.run(
                    ["git", *args],
                    cwd=lineage,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return result.stdout.strip()

            git("init", "-q")
            git("config", "user.email", "test@example.invalid")
            git("config", "user.name", "test")
            (lineage / "README").write_text("fixture\n", encoding="utf-8")
            (lineage / "LICENSE").write_text("license pending review\n", encoding="utf-8")
            git("add", "README", "LICENSE")
            git("commit", "-q", "-m", "fixture")
            commit = git("rev-parse", "HEAD")
            git("remote", "add", "origin", "https://Example.invalid/Org/Demo.git")
            lock = {
                "lineages": [{
                    "lineage_id": "demo",
                    "repository": "https://example.invalid/org/demo.git",
                    "commit": commit,
                    "split": "development",
                }]
            }
            (root / "dataset" / "sources" / "source_lock.json").write_text(
                json.dumps(lock), encoding="utf-8"
            )
            report = audit_source_cache.audit(root, cache)
            row = report["lineages"][0]
            self.assertEqual(row["status"], "PASS")
            self.assertTrue(row["remote_match"])
            self.assertEqual(row["tracked_license_paths"], ["LICENSE"])
            self.assertEqual(row["license_review_status"], "pending_component_review")


if __name__ == "__main__":
    unittest.main()
