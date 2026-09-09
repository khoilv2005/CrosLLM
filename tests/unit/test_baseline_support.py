from __future__ import annotations

import unittest

from crossllm.baselines import SupportEntry, SupportMatrix, SupportStatus


class BaselineSupportTests(unittest.TestCase):
    def test_unreviewed_matrix_round_trips_with_deterministic_hash(self) -> None:
        matrix = SupportMatrix(
            "native-baselines-v1",
            (
                SupportEntry("slither", "solidity-evm", SupportStatus.SUPPORTED, "smoke fixture", "a" * 64),
                SupportEntry("ityfuzz", "solidity-evm", SupportStatus.CONDITIONAL, "version-specific", None),
            ),
        )
        payload = matrix.as_dict()
        restored = SupportMatrix.from_dict(payload)
        self.assertEqual(restored, matrix)
        self.assertEqual(len(matrix.matrix_hash), 64)

    def test_owner_accepted_matrix_requires_evidence_for_every_entry(self) -> None:
        with self.assertRaisesRegex(ValueError, "evidence hash"):
            SupportMatrix(
                "reviewed",
                (SupportEntry("slither", "scope", SupportStatus.SUPPORTED, "reason"),),
                acceptance_status="owner_accepted",
                acceptance_owner="project-owner",
                accepted_at="2026-09-08",
                acceptance_agent="codex",
            )

    def test_coverage_keeps_unsupported_rows_in_denominator(self) -> None:
        matrix = SupportMatrix("coverage", ())
        coverage = matrix.coverage(
            [
                {"instance_id": "a", "supported_methods": ["slither", "ityfuzz"]},
                {"instance_id": "b", "supported_methods": ["slither"]},
            ],
            methods=("slither", "ityfuzz"),
        )
        self.assertEqual(coverage["methods"]["ityfuzz"]["denominator"], 2)
        self.assertEqual(coverage["methods"]["ityfuzz"]["unsupported"], 1)
        self.assertEqual(coverage["common_supported_record_ids"], ["a"])


if __name__ == "__main__":
    unittest.main()
