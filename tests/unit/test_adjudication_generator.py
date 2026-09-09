from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import generate_adjudication_records


class AdjudicationGeneratorTests(unittest.TestCase):
    def test_refuses_to_fabricate_labels_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "records.jsonl"
            self.assertEqual(generate_adjudication_records.main(["--out", str(output)]), 2)
            self.assertFalse(output.exists())

    def test_explicit_synthetic_mode_only_writes_pending_templates(self) -> None:
        manifest = [
            {
                "instance_id": "synthetic-1",
                "lineage_id": "lineage-1",
                "property_family": "replay",
                "cohort": "sealed",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.jsonl"
            output = root / "nested" / "records.jsonl"
            manifest_path.write_text(json.dumps(manifest[0]) + "\n", encoding="utf-8")

            self.assertEqual(
                generate_adjudication_records.main([
                    "--manifest", str(manifest_path),
                    "--out", str(output),
                    "--allow-synthetic-template",
                ]),
                0,
            )
            record = json.loads(output.read_text(encoding="utf-8").strip())
            self.assertEqual(record["record_status"], "template_pending_independent_review")
            self.assertEqual(record["provenance_status"], "synthetic_template_not_evidence")
            self.assertEqual(record["labels"], [])
            self.assertIsNone(record["reconciliation"])
            self.assertNotIn("VERIFIED_VALID", output.read_text(encoding="utf-8"))
            self.assertNotIn("ADMITTED", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
