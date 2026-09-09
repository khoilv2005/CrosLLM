from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from scripts import build_development_support_matrix


ROOT = Path(__file__).parents[2]


class DevelopmentSupportMatrixTests(unittest.TestCase):
    def test_non_celer_host_matrices_are_schema_valid_and_draft_only(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "evm_support_matrix.schema.json").read_text(
                encoding="utf-8"
            )
        )
        # The generic report schema is intentionally separate from the legacy
        # Celer schema, but both reports use the same matrix object contract.
        generic_schema = json.loads(
            (ROOT / "schemas" / "development_evm_support_matrix.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("properties", schema)
        for lineage in build_development_support_matrix.LINEAGES:
            report = json.loads(
                (ROOT / "dataset" / "reports" / f"evm_support_matrix_{lineage}.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(list(Draft202012Validator(generic_schema).iter_errors(report)), [])
            self.assertEqual(build_development_support_matrix.validate_report(ROOT, lineage), [])
            self.assertEqual(report["lineage_id"], lineage)
            self.assertEqual(report["matrix"]["acceptance_status"], "draft")
            self.assertFalse(report["admission_eligible"])

    def test_matrix_report_hash_and_bytecode_scan_are_tamper_checked(self) -> None:
        report = json.loads(
            (ROOT / "dataset" / "reports" / "evm_support_matrix_chainbridge.json").read_text(
                encoding="utf-8"
            )
        )
        report["bytecode_opcode_scan"]["unique_opcodes"].append("FAKE")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            errors = build_development_support_matrix.validate_report(
                ROOT, "chainbridge", path
            )
        self.assertIn("support matrix report hash mismatch", errors)
        self.assertIn("bytecode_opcode_scan mismatch", errors)


if __name__ == "__main__":
    unittest.main()
