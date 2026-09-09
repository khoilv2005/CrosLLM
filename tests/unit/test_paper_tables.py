from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.update_paper_tables import update_paper


class PaperTableUpdateTests(unittest.TestCase):
    def test_updates_only_marked_region_and_keeps_missing_inference_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paper = root / "paper.tex"
            artifact = root / "analysis.json"
            paper.write_text(
                "prefix\n% BEGIN GENERATED:tab:main-v2\nold\n% END GENERATED:tab:main-v2\nsuffix\n",
                encoding="utf-8",
            )
            artifact.write_text(json.dumps({
                "analysis": {
                    "methods": ["X"],
                    "recall": {"X": {"value": 0.5, "known": 1, "total": 2}},
                    "native_witness_yield": {"X": {"value": None}},
                },
            }), encoding="utf-8")
            update_paper(paper, artifact)
            output = paper.read_text(encoding="utf-8")
            self.assertIn("X & development/evaluation & 1/2 & 0.5", output)
            self.assertIn(r"\ResultTBD", output)
            self.assertTrue(output.startswith("prefix\n"))
            self.assertTrue(output.endswith("suffix\n"))


if __name__ == "__main__":
    unittest.main()
