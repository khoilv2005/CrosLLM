from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from dataset.tools import extract_all_artifacts, verify_artifact_provenance


class ArtifactProvenanceTests(unittest.TestCase):
    def _write_valid_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        spec = extract_all_artifacts.LINEAGE_SPECS["celer_cbridge"]
        source_cache = root / "sources"
        source_file = source_cache / "celer_cbridge" / "contracts" / "CBridge.sol"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("contract CBridge {}\n", encoding="utf-8")
        dependency_file = (
            source_cache / "celer_cbridge" / "node_modules" / "example" / "package.json"
        )
        dependency_file.parent.mkdir(parents=True)
        dependency_file.write_text('{"name":"example"}\n', encoding="utf-8")

        repo_root = root / "repo"
        artifact_root = repo_root / "dataset" / "artifacts" / "celer_cbridge"
        artifact_root.mkdir(parents=True)
        (repo_root / "dataset" / "sources").mkdir(parents=True)
        (repo_root / "dataset" / "sources" / "source_lock.json").write_text(
            json.dumps({"lineages": [{
                "lineage_id": "celer_cbridge",
                "commit": spec["commit"],
            }]}),
            encoding="utf-8",
        )

        artifact_values = {
            "abi/CBridge.json": "[]\n",
            "bytecode/CBridge.creation.hex": "0x6000\n",
            "bytecode/CBridge.deployed.hex": "0x6000\n",
            "storage_layout/CBridge.json": '{"storage":[]}\n',
        }
        hashes: dict[str, str] = {}
        for relative, value in artifact_values.items():
            path = artifact_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8")
            hashes[relative] = extract_all_artifacts._file_hash(path)

        settings = {
            "compiler": "solc",
            "compiler_version": spec["solc"],
            "optimizer": True,
            "optimizer_runs": spec["optimizer_runs"],
            "build_framework": "foundry",
        }
        source_hash = extract_all_artifacts._file_hash(source_file)
        source_target = extract_all_artifacts.source_target_metadata(source_file, "CBridge")
        selection = extract_all_artifacts.deterministic_source_selection(
            source_cache / "celer_cbridge", "", spec["contracts"]
        )
        (artifact_root / "build_info.json").write_text(json.dumps({
            "compiler_settings": settings,
            "compiler_settings_sha256": extract_all_artifacts._canonical_hash(settings),
            "source_selection_hash": selection["selection_hash"],
            "dependency_closure": extract_all_artifacts.dependency_closure(
                source_cache / "celer_cbridge"
            ),
        }), encoding="utf-8")
        (artifact_root / "symbols.json").write_text(json.dumps({
            "contracts": {"CBridge": {
                "source_file_sha256": source_hash,
                "source_target": source_target,
            }},
            "stable_symbols": [],
            "stable_symbols_sha256": extract_all_artifacts._canonical_hash([]),
            "domain_assignments": {"CBridge": "shared"},
        }), encoding="utf-8")
        (artifact_root / "selection.json").write_text(json.dumps(selection), encoding="utf-8")
        (artifact_root / "deployment.json").write_text(json.dumps({
            "contracts": {"CBridge": {
                "source_target": source_target,
                "abi_path": "abi/CBridge.json",
                "abi_sha256": hashes["abi/CBridge.json"],
                "creation_bytecode_path": "bytecode/CBridge.creation.hex",
                "creation_bytecode_sha256": hashes["bytecode/CBridge.creation.hex"],
                "deployed_bytecode_path": "bytecode/CBridge.deployed.hex",
                "deployed_bytecode_sha256": hashes["bytecode/CBridge.deployed.hex"],
                "storage_layout_path": "storage_layout/CBridge.json",
                "storage_layout_sha256": hashes["storage_layout/CBridge.json"],
                "constructor_args": [],
                "constructor_args_sha256": extract_all_artifacts._canonical_hash([]),
                "initializer_args": [],
                "initializer_args_sha256": extract_all_artifacts._canonical_hash([]),
            }},
        }), encoding="utf-8")
        (artifact_root / "source_receipt.json").write_text(json.dumps({
            "source_commit": spec["commit"],
            "source_repo": spec["source_repo"],
        }), encoding="utf-8")
        return repo_root, source_cache, artifact_root

    def test_valid_pack_passes_diagnostic_provenance_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo, source_cache, _ = self._write_valid_fixture(Path(temporary))
            report = verify_artifact_provenance.verify(
                repo, source_cache, ("celer_cbridge",)
            )
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["lineages"][0]["errors"], [])

    def test_artifact_tampering_is_reported_without_admission_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo, source_cache, artifact_root = self._write_valid_fixture(Path(temporary))
            abi = artifact_root / "abi" / "CBridge.json"
            abi.write_text("[tampered]\n", encoding="utf-8")
            report = verify_artifact_provenance.verify(
                repo, source_cache, ("celer_cbridge",)
            )
            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(any(
                "abi_sha256 mismatch" in error
                for error in report["lineages"][0]["errors"]
            ))
            self.assertFalse((repo / "dataset" / "benchmark_admission.json").exists())

    def test_default_source_cache_is_relative_to_resolved_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repo, _, _ = self._write_valid_fixture(base)
            source_cache = base / "crossllm_private_sources" / "celer_cbridge" / "contracts"
            source_cache.mkdir(parents=True)
            (source_cache / "CBridge.sol").write_text("contract CBridge {}\n", encoding="utf-8")
            dependency = source_cache.parent / "node_modules" / "example" / "package.json"
            dependency.parent.mkdir(parents=True)
            dependency.write_text('{"name":"example"}\n', encoding="utf-8")
            source_cache = source_cache.parent.parent
            nested = repo / "nested"
            nested.mkdir()
            # Passing a relative root must resolve before deriving its sibling
            # source cache; this mirrors `--root .` from a repository checkout.
            import os
            previous = Path.cwd()
            try:
                os.chdir(repo.parent)
                report = verify_artifact_provenance.verify(Path("repo"), None, ("celer_cbridge",))
            finally:
                os.chdir(previous)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["lineages"][0]["source_root"], str(source_cache / "celer_cbridge"))

    def test_dependency_tampering_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo, source_cache, _ = self._write_valid_fixture(Path(temporary))
            dependency = source_cache / "celer_cbridge" / "node_modules" / "example" / "package.json"
            dependency.write_text('{"name":"tampered"}\n', encoding="utf-8")
            report = verify_artifact_provenance.verify(
                repo, source_cache, ("celer_cbridge",)
            )
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("dependency_closure mismatch", report["lineages"][0]["errors"])

    def test_source_selection_tampering_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo, source_cache, artifact_root = self._write_valid_fixture(Path(temporary))
            selection = json.loads((artifact_root / "selection.json").read_text(encoding="utf-8"))
            selection["selected_paths"] = []
            (artifact_root / "selection.json").write_text(json.dumps(selection), encoding="utf-8")
            report = verify_artifact_provenance.verify(
                repo, source_cache, ("celer_cbridge",)
            )
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("source selection mismatch", report["lineages"][0]["errors"])

    def test_stable_symbol_forgery_is_reported_after_recomputation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo, source_cache, artifact_root = self._write_valid_fixture(Path(temporary))
            symbols_path = artifact_root / "symbols.json"
            symbols = json.loads(symbols_path.read_text(encoding="utf-8"))
            symbols["stable_symbols"] = [{"symbol_id": "forged.symbol"}]
            symbols["stable_symbols_sha256"] = extract_all_artifacts._canonical_hash(
                symbols["stable_symbols"]
            )
            symbols_path.write_text(json.dumps(symbols), encoding="utf-8")
            report = verify_artifact_provenance.verify(
                repo, source_cache, ("celer_cbridge",)
            )
            self.assertEqual(report["status"], "FAIL")
            self.assertIn(
                "stable_symbols do not match ABI/storage artifacts and explicit domains",
                report["lineages"][0]["errors"],
            )


if __name__ == "__main__":
    unittest.main()
