from __future__ import annotations

import unittest

from scripts import validate_dataset


class StrictDatasetValidatorTests(unittest.TestCase):
    def test_current_starter_passes_local_integrity_but_blocks_admission(self) -> None:
        self.assertEqual(validate_dataset._local_integrity(), [])
        blockers = validate_dataset._admission_blockers()
        self.assertTrue(blockers)
        self.assertTrue(any("ancestry review" in item for item in blockers))
        self.assertFalse(any("source_backed" in item for item in blockers))
        self.assertTrue(any("EVALUATION_LOCKED" in item for item in blockers))
        self.assertTrue(any("final-manifest validator" in item for item in blockers))

    def test_development_mutation_receipt_is_hash_and_scope_checked(self) -> None:
        self.assertEqual(validate_dataset._development_mutation_evidence_errors(), [])


if __name__ == "__main__":
    unittest.main()
