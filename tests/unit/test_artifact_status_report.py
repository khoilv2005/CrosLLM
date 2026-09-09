from __future__ import annotations

import unittest

from dataset.tools import gen_artifact_status


class ArtifactStatusReportTests(unittest.TestCase):
    def test_report_is_derived_from_current_packs_and_stays_non_admission(self) -> None:
        report = gen_artifact_status.build_report()
        self.assertIn("`SendUln302`", report)
        self.assertIn("`CBridge`", report)
        self.assertIn("`Bridge`, `ERC20Handler`", report)
        self.assertIn("NOT EXPERIMENT READY", report)
        self.assertIn("Build probes and non-empty bytecode do not establish", report)
        self.assertIn("lock=locked_commit_only", report)
        self.assertNotIn("EndpointV2` |", report)


if __name__ == "__main__":
    unittest.main()
