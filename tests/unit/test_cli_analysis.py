from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from crossllm.cli import main


class CLIAnalysisTests(unittest.TestCase):
    def test_analysis_build_writes_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw.jsonl"
            out = root / "analysis.json"
            raw.write_text(json.dumps({
                "campaign_id": "c1", "instance_id": "i1", "lineage_id": "l1",
                "method": "X", "replicate": 1, "ground_truth": "positive", "detected": True,
            }) + "\n", encoding="utf-8")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = main(["analysis-build", "--raw", str(raw), "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertTrue(out.exists())
            self.assertEqual(json.loads(stream.getvalue())["row_count"], 1)

    def test_analysis_build_accepts_strict_primary_and_secondary_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw.jsonl"
            out = root / "analysis.json"
            primary = root / "primary.json"
            secondary = root / "secondary.json"
            raw.write_text(json.dumps({
                "campaign_id": "c1", "instance_id": "i1", "lineage_id": "l1",
                "method": "X", "replicate": 1, "ground_truth": "positive", "detected": True,
            }) + "\n", encoding="utf-8")
            primary.write_text(json.dumps({f"p{index}": {"l1": 1.0} for index in range(5)}), encoding="utf-8")
            secondary.write_text(json.dumps({f"s{index}": {"l1": 0.0} for index in range(6)}), encoding="utf-8")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = main([
                    "analysis-build", "--raw", str(raw), "--out", str(out),
                    "--primary-contrasts", str(primary), "--secondary-contrasts", str(secondary),
                    "--require-prespecified-families", "--draws", "5",
                ])
            self.assertEqual(code, 0)
            payload = json.loads(stream.getvalue())
            self.assertEqual(len(payload["primary_inference"]), 5)
            self.assertEqual(len(payload["secondary_inference"]), 6)


if __name__ == "__main__":
    unittest.main()
