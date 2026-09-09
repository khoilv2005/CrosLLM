from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from crossllm.cli import main


class CLIFigureTests(unittest.TestCase):
    def test_analysis_figures_writes_svg_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = root / "figures.json"
            out = root / "out"
            spec.write_text(json.dumps({"failure_flow": {"timeout": 2}}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as stream:
                code = main(["analysis-figures", "--spec", str(spec), "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertTrue((out / "failure_flow.svg").exists())
            self.assertEqual(len(json.loads(stream.getvalue())["figures"]), 1)


if __name__ == "__main__":
    unittest.main()
