from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from crossllm.cli import main


class CLIAdjudicationTests(unittest.TestCase):
    def test_export_then_import_labels_keeps_blinded_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            findings = root / "findings.json"
            blinded = root / "blinded.json"
            labels = root / "labels.json"
            ledger = root / "ledger.json"
            findings.write_text(json.dumps({
                "findings": [{
                    "finding_id": "f1",
                    "instance_id": "i1",
                    "claim": {"location": "Bridge.send"},
                }],
            }), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["adjudication-export", "--findings", str(findings), "--out", str(blinded)]), 0)
            exported = json.loads(blinded.read_text(encoding="utf-8"))
            labels.write_text(json.dumps({
                "schema_version": 1,
                "finding_export_id": exported["export_id"],
                "method_identity_included": False,
                "labels": [{
                    "finding_id": "f1", "rater_id": "r1", "role": "expert",
                    "status": "confirmed", "first_failure": "true_vulnerability",
                    "uncertainty_reason": None, "confidence": "high",
                    "label_version": "v1", "created_at": "t",
                }],
            }), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([
                    "adjudication-import", "--blinded", str(blinded),
                    "--labels", str(labels), "--out", str(ledger),
                ]), 0)
            imported = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(imported["findings"][0]["finding_id"], "f1")
            self.assertEqual(imported["labels"][0]["rater_id"], "r1")
            self.assertFalse(imported["findings"][0].get("method_identity_included", False))


if __name__ == "__main__":
    unittest.main()
