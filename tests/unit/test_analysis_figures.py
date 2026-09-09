from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crossllm.analysis import AnalysisFigureBuilder, write_figure_bundle


class AnalysisFigureTests(unittest.TestCase):
    def test_requested_figures_are_deterministic_and_hash_linked(self) -> None:
        kwargs = {
            "paired_lineage": {"l2": -0.1, "l1": 0.2},
            "recall_at_n": {"P": {1: 0.1, 2: 0.4}, "X": {1: 0.2, 2: 0.5}},
            "time_curves": {"X": [(1.0, 0.1), (2.0, 0.5)]},
            "scaling": {"X": {10: 0.2, 20: 0.4}},
            "failure_flow": {"timeout": 2, "replay_failure": 1},
        }
        first = AnalysisFigureBuilder().build(**kwargs)
        second = AnalysisFigureBuilder().build(**kwargs)
        self.assertEqual(first, second)
        self.assertEqual([figure.figure_id for figure in first], [
            "paired_lineage", "recall_at_n", "time_curves", "scaling", "failure_flow",
        ])
        self.assertTrue(all(figure.source_hash and figure.svg_hash for figure in first))
        with tempfile.TemporaryDirectory() as directory:
            manifest = write_figure_bundle(first, Path(directory))
            self.assertTrue(manifest.exists())
            self.assertTrue((Path(directory) / "recall_at_n.svg").exists())

    def test_missing_series_emit_no_fabricated_figure_and_invalid_probability_rejects(self) -> None:
        self.assertEqual(AnalysisFigureBuilder().build(), ())
        with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
            AnalysisFigureBuilder().build(recall_at_n={"X": {1: 1.1}})


if __name__ == "__main__":
    unittest.main()
