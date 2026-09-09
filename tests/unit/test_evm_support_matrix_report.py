from __future__ import annotations

import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from scripts import build_evm_support_matrix


ROOT = Path(__file__).parents[2]


class EVMSupportMatrixReportTests(unittest.TestCase):
    def test_report_matches_schema_and_locked_inputs(self) -> None:
        schema = json.loads((ROOT / "schemas" / "evm_support_matrix.schema.json").read_text(encoding="utf-8"))
        report = json.loads((ROOT / "dataset" / "reports" / "evm_support_matrix_celer_cbridge.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(report)), [])
        self.assertEqual(build_evm_support_matrix.validate_report(ROOT), [])
        self.assertFalse(report["admission_eligible"])
        self.assertEqual(report["acceptance_status"], "draft")
        self.assertTrue(report["matrix"]["matrix_hash"])
        self.assertIn("opcode", {row["category"] for row in report["matrix"]["entries"]})
        self.assertIn("precompile", {row["category"] for row in report["matrix"]["entries"]})
        self.assertIn("proxy", {row["category"] for row in report["matrix"]["entries"]})
        self.assertIn("crypto", {row["category"] for row in report["matrix"]["entries"]})

    def test_tampering_the_opcode_scan_is_detected(self) -> None:
        report = json.loads((ROOT / "dataset" / "reports" / "evm_support_matrix_celer_cbridge.json").read_text(encoding="utf-8"))
        report["bytecode_opcode_scan"]["unique_opcodes"].append("FAKE")
        self.assertIn(
            "bytecode opcode scan mismatch",
            build_evm_support_matrix.validate_report(ROOT, _write_temp_report(report)),
        )


def _write_temp_report(report: dict[str, object]) -> Path:
    import tempfile

    directory = Path(tempfile.mkdtemp(prefix="crossllm-support-matrix-"))
    path = directory / "matrix.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


if __name__ == "__main__":
    unittest.main()
