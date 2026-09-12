from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from crossllm.verification.source_workspace import materialize_source_case_workspace


class SourceWorkspaceTests(unittest.TestCase):
    def _fixture(self) -> tuple[Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        harness = root / "dataset" / "harness" / "demo"
        (harness / "contracts").mkdir(parents=True)
        (harness / "test").mkdir(parents=True)
        (harness / "contracts" / "Bridge.sol").write_text("contract BaseBridge {}\n", encoding="utf-8")
        (harness / "test" / "Base.t.sol").write_text("contract BaseTest {}\n", encoding="utf-8")
        case = root / "dataset" / "artifacts" / "demo" / "cases" / "case_01"
        (case / "runtime" / "source").mkdir(parents=True)
        (case / "runtime" / "test").mkdir(parents=True)
        source = case / "runtime" / "source" / "Bridge.sol"
        test = case / "runtime" / "test" / "ReplayEvidence.t.sol"
        source.write_text("contract MutatedBridge {}\n", encoding="utf-8")
        test.write_text("import \"./Base.t.sol\";\ncontract ReplayEvidence {}\n", encoding="utf-8")
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path, payload in {
            case / "metadata.json": {"lineage_id": "demo", "instance_id": "case_01", "split": "development", "built_source_sha256": digest(source)},
            case / "build_manifest.json": {"source": {"path": "runtime/source/Bridge.sol", "sha256": digest(source)}},
            case / "paired_harness.json": {"test": {"path": "runtime/test/ReplayEvidence.t.sol", "sha256": digest(test)}},
            case / "source_identity.json": {"lineage_id": "demo", "upstream_source_path": "contracts/Bridge.sol"},
        }.items():
            path.write_text(json.dumps(payload), encoding="utf-8")
        return root, case

    def test_materializes_clean_workspace_and_overlays_case_files(self) -> None:
        root, case = self._fixture()
        with materialize_source_case_workspace(root, "demo", "case_01") as (workspace, identity):
            self.assertEqual(identity.case_id, "case_01")
            self.assertEqual((workspace / "contracts" / "Bridge.sol").read_text(encoding="utf-8"), "contract MutatedBridge {}\n")
            self.assertTrue((workspace / "test" / "ReplayEvidence.t.sol").is_file())
            self.assertTrue((workspace / "test" / "Base.t.sol").is_file())
            self.assertFalse((workspace / "out").exists())
        self.assertFalse(workspace.exists())

    def test_rejects_case_path_escape(self) -> None:
        root, case = self._fixture()
        build = json.loads((case / "build_manifest.json").read_text(encoding="utf-8"))
        build["source"]["path"] = "../outside.sol"
        (case / "build_manifest.json").write_text(json.dumps(build), encoding="utf-8")
        with self.assertRaises(ValueError):
            with materialize_source_case_workspace(root, "demo", "case_01"):
                pass

    def test_rejects_source_hash_mismatch(self) -> None:
        root, case = self._fixture()
        metadata = json.loads((case / "metadata.json").read_text(encoding="utf-8"))
        metadata["built_source_sha256"] = "0" * 64
        (case / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaises(ValueError):
            with materialize_source_case_workspace(root, "demo", "case_01"):
                pass


if __name__ == "__main__":
    unittest.main()
