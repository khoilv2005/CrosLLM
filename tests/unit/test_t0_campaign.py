import tempfile
import unittest
from pathlib import Path

from crossllm.methods import T0DeterministicProposer, T0Template, T0TemplateLibrary
from crossllm.verification import load_archives
from scripts.run_t0_campaign import build_t0_archive, write_t0_campaign


class T0CampaignTests(unittest.TestCase):
    def test_providerless_t0_archive_round_trips_through_shared_loader(self) -> None:
        pack = {
            "schema_version": 1,
            "record_type": "public_evaluation_artifact_pack",
            "public_files": {"storage_symbols.json": {"schema_version": 1, "symbols": [
                {"symbol_id": "storage.B.slot_0.flag", "path": "B.sol", "name": "flag", "domain": "source", "kind": "storage", "type": "bool"},
            ]}},
            "gold_access": "disabled",
        }
        library = T0TemplateLibrary(
            "t0-campaign-test-v1", 8,
            (T0Template("state-stability", "invariant", "eq", "pre", "post", "sorted_public_scalar_storage_symbols"),),
        )
        run = T0DeterministicProposer(library).propose(pack, attempt_id="t0-attempt")
        archive = build_t0_archive(
            pack,
            run,
            campaign_id="t0-campaign",
            lineage_id="lineage",
            instance_id="instance",
            replicate=1,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t0" / "t0-campaign" / "campaigns.jsonl"
            write_t0_campaign(path, archive)
            loaded = load_archives({"t0": path.parent.parent})
        self.assertEqual(len(loaded.campaigns), 1)
        self.assertEqual(loaded.campaigns[0].candidate_count, 1)
        self.assertEqual(loaded.campaigns[0].provider_failure_count, 0)
        self.assertEqual(loaded.campaigns[0].candidate_inputs()[0].raw_response, {})
        self.assertEqual(archive["method_run"]["provider_responses"], [])


if __name__ == "__main__":
    unittest.main()
