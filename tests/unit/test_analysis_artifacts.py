from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crossllm.analysis import AnalysisArtifactBuilder, AnalysisInputError, load_campaign_jsonl


def rows() -> list[dict[str, object]]:
    return [
        {"campaign_id": "c1", "instance_id": "i1", "lineage_id": "l1", "method": "X", "replicate": 1, "ground_truth": "positive", "detected": True, "native_witness": True, "claim_time_seconds": 1.0, "horizon_seconds": 10},
        {"campaign_id": "c2", "instance_id": "i1", "lineage_id": "l1", "method": "P", "replicate": 1, "ground_truth": "positive", "detected": False, "native_witness": None, "claim_time_seconds": None, "horizon_seconds": 10, "availability": "timeout"},
        {"campaign_id": "c3", "instance_id": "i2", "lineage_id": "l2", "method": "X", "replicate": 1, "ground_truth": "negative", "claim_emitted": False},
    ]


class AnalysisArtifactTests(unittest.TestCase):
    def test_reordering_has_same_hash_and_missingness_is_retained(self) -> None:
        builder = AnalysisArtifactBuilder()
        first = builder.build(rows())
        second = builder.build(list(reversed(rows())))
        self.assertEqual(first.input_hash, second.input_hash)
        self.assertEqual(first.artifact_hash, second.artifact_hash)
        self.assertEqual(first.report.native_witness_yield["P"].missing, 1)
        self.assertEqual(len(first.tables), 11)
        self.assertEqual(first.tables[0].table_id, "recall")

    def test_malformed_raw_row_is_rejected(self) -> None:
        with self.assertRaises(AnalysisInputError):
            AnalysisArtifactBuilder().build([{"campaign_id": "only-id"}])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.jsonl"
            path.write_text("not-json\n", encoding="utf-8")
            with self.assertRaises(AnalysisInputError):
                load_campaign_jsonl(path)

    def test_artifact_can_be_written_as_json(self) -> None:
        artifact = AnalysisArtifactBuilder().build(rows(), primary_contrasts={"X-minus-P": {"l1": 1.0, "l2": 0.0}})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "analysis.json"
            artifact.write_json(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["input_hash"], artifact.input_hash)
            self.assertEqual(payload["primary_inference"][0]["contrast"], "X-minus-P")
            self.assertEqual(len(payload["tables"]), 11)

    def test_builder_preserves_paired_method_effects(self) -> None:
        artifact = AnalysisArtifactBuilder().build(rows(), compare_methods=("X", "P"))
        self.assertIn("X-minus-P", artifact.report.paired_effects)

    def test_bundle_writes_all_tables_and_hash_manifest(self) -> None:
        artifact = AnalysisArtifactBuilder().build(rows())
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = artifact.write_bundle(Path(directory) / "bundle")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["input_hash"], artifact.input_hash)
            self.assertEqual(len(manifest["tables"]), 11)
            for table in manifest["tables"]:
                table_path = manifest_path.parent / table["path"]
                self.assertTrue(table_path.is_file())
                self.assertEqual(len(table["sha256"]), 64)

    def test_strict_inference_requires_separate_prespecified_family_sizes(self) -> None:
        builder = AnalysisArtifactBuilder()
        with self.assertRaisesRegex(AnalysisInputError, "exactly 5"):
            builder.build(rows(), require_prespecified_families=True)
        primary = {f"primary-{index}": {"l1": 1.0, "l2": -1.0} for index in range(5)}
        secondary = {f"secondary-{index}": {"l1": 0.0, "l2": 1.0} for index in range(6)}
        artifact = builder.build(
            rows(),
            primary_contrasts=primary,
            secondary_contrasts=secondary,
            require_prespecified_families=True,
            draws=25,
        )
        self.assertEqual(len(artifact.primary_inference), 5)
        self.assertEqual(len(artifact.secondary_inference), 6)
        self.assertEqual({item.adjusted_p_value for item in artifact.primary_inference}, {1.0})


if __name__ == "__main__":
    unittest.main()
