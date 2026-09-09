from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "prepare_development_campaign.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("crossllm_prepare_development_campaign", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load development campaign preparation script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrepareDevelopmentCampaignTests(unittest.TestCase):
    def test_bundle_is_source_backed_development_only_and_hash_bound(self) -> None:
        module = _load_script()
        with tempfile.TemporaryDirectory() as directory:
            manifest = module.build_bundle(
                root=ROOT,
                out_dir=Path(directory) / "campaign",
                created_at="2026-09-09T00:00:00Z",
            )
            self.assertEqual(manifest["status"], "development_execution_input")
            self.assertFalse(manifest["admission_eligible"])
            self.assertFalse(manifest["sealed_data_read"])
            self.assertEqual(manifest["campaign_count"], 36)
            self.assertIsNone(json.loads((Path(directory) / "campaign/config.json").read_text())["benchmark_manifest_hash"])
            plan = json.loads((Path(directory) / "campaign/campaigns.plan.json").read_text())
            self.assertEqual(plan["mode"], "development")
            self.assertIsNone(plan["benchmark_manifest_hash"])
            self.assertEqual(len(plan["campaigns"]), 36)
            self.assertEqual(
                sorted(row["lineage_id"] for row in plan["campaigns"])[0],
                "celer_cbridge",
            )
            for lineage in module.DEVELOPMENT_LINEAGES:
                pack = json.loads((Path(directory) / f"campaign/artifact_packs/{lineage}.json").read_text())
                self.assertFalse(pack["admission_eligible"])
                self.assertIn("storage_symbols.json", pack["public_files"])
                self.assertNotIn("ground_truth", json.dumps(pack).lower())

    def test_non_empty_output_is_never_overwritten(self) -> None:
        module = _load_script()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "campaign"
            output.mkdir()
            (output / "sentinel").write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                module.build_bundle(root=ROOT, out_dir=output)

    def test_evaluation_family_or_method_cannot_enter_bundle(self) -> None:
        module = _load_script()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "subset"):
                module.build_bundle(root=ROOT, out_dir=Path(directory) / "campaign", methods=("X", "evaluation"))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "subset"):
                module.build_bundle(root=ROOT, out_dir=Path(directory) / "campaign", families=("GLM", "sealed"))

    def test_bundle_can_narrow_to_one_source_backed_lineage(self) -> None:
        module = _load_script()
        with tempfile.TemporaryDirectory() as directory:
            manifest = module.build_bundle(
                root=ROOT,
                out_dir=Path(directory) / "campaign",
                lineages=("chainbridge",),
                families=("gpt-oss",),
                methods=("T0",),
                created_at="2026-09-09T00:00:00Z",
            )
            self.assertEqual(manifest["lineages"], ["chainbridge"])
            self.assertEqual(manifest["campaign_count"], 1)


if __name__ == "__main__":
    unittest.main()
