from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from scripts import run_provider_contract_rehearsal


ROOT = Path(__file__).resolve().parents[2]


class ProviderContractRehearsalTests(unittest.TestCase):
    def test_rehearsal_covers_m06_and_never_claims_cloud_execution(self) -> None:
        report = run_provider_contract_rehearsal.build_report(ROOT)
        schema = json.loads((ROOT / "schemas/provider_contract_rehearsal.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(report)), [])
        self.assertTrue(report["all_passed"])
        self.assertEqual(report["case_count"], 9)
        self.assertEqual(report["ollama_cloud_calls"], 0)
        self.assertTrue(report["fake_server_only"])
        self.assertFalse(report["admission_eligible"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provider-contract.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            self.assertEqual(run_provider_contract_rehearsal.validate_report(ROOT, path), [])

    def test_tampered_report_is_rejected(self) -> None:
        report = run_provider_contract_rehearsal.build_report(ROOT)
        report["ollama_cloud_calls"] = 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provider-contract.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            errors = run_provider_contract_rehearsal.validate_report(ROOT, path)
        self.assertIn("provider contract rehearsal report hash mismatch", errors)
        self.assertIn("ollama_cloud_calls mismatch", errors)


if __name__ == "__main__":
    unittest.main()
