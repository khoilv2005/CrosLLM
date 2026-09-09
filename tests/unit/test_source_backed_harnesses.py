import json
from pathlib import Path
import tempfile
import unittest

from scripts import source_backed_harnesses


class SourceBackedHarnessTests(unittest.TestCase):
    def test_layerzero_mocks_map_to_locked_upstream_test_mocks(self) -> None:
        self.assertEqual(
            source_backed_harnesses._source_rel_for_harness(
                "contracts/mocks/AppMock.sol",
                "packages/layerzero-v2/evm/protocol",
            ),
            "packages/layerzero-v2/evm/protocol/test/mocks/AppMock.sol",
        )

    def test_wormhole_contract_alias_maps_to_src_root(self) -> None:
        self.assertEqual(
            source_backed_harnesses._source_rel_for_harness(
                "contracts/proxy/Proxy.sol",
                "src",
                "contracts/",
            ),
            "src/proxy/Proxy.sol",
        )

    def test_foundry_json_counts_only_explicit_test_results(self) -> None:
        payload = {
            "suite": {
                "test_results": {
                    "test_ok()": {"status": "Success"},
                    "test_bad()": {"status": "Failure"},
                }
            }
        }
        total, passed, failed = source_backed_harnesses._count_foundry_tests(
            json.dumps(payload)
        )
        self.assertEqual((total, passed, failed), (2, 1, 1))

    def test_workflow_coverage_has_all_m02_06_dimensions(self) -> None:
        required = {
            "state_initialization", "normal_workflow", "allowed_actions", "clocks",
            "finality", "attestation", "callbacks", "reset_isolation",
        }
        for lineage, layout in source_backed_harnesses.HARNESS_LAYOUT.items():
            self.assertEqual(set(layout["workflow"]), required, lineage)
            self.assertFalse(
                layout["workflow"]["reset_isolation"]["cross_test_state_reuse"],
                lineage,
            )

    def test_failed_probe_cannot_finalize_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "non-passing probe"):
                source_backed_harnesses.finalize_source_backed_metadata(
                    "celer_cbridge",
                    {},
                    {"status": "fail"},
                    root=Path(temporary),
                )


if __name__ == "__main__":
    unittest.main()
