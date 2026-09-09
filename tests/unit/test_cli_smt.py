from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from crossllm.cli import main


class CLISMTTests(unittest.TestCase):
    def test_xlir_smt_check_emits_solver_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            symbols = root / "symbols.json"
            proposal = root / "proposal.json"
            symbols.write_text(json.dumps({"symbols": [
                {"symbol_id": "sym.flag", "path": "Bridge.sol", "name": "flag", "domain": "source", "kind": "storage", "type": "bool"},
            ]}), encoding="utf-8")
            proposal.write_text(json.dumps({
                "kind": "invariant",
                "body": {
                    "kind": "binary", "operator": "eq",
                    "left": {"kind": "symbol", "symbol_id": "sym.flag", "state": "post"},
                    "right": {"kind": "symbol", "symbol_id": "sym.flag", "state": "post"},
                },
            }), encoding="utf-8")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                exit_code = main([
                    "xlir-smt-check",
                    "--symbols", str(symbols),
                    "--proposal", str(proposal),
                ])
            output = json.loads(stream.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(output["ok"])
            self.assertEqual(output["solver_result"]["status"], "bounded_unsat")
            self.assertTrue(output["solver_result"]["complete"])

    def test_xlir_smt_check_accepts_explicit_temporal_trace_length(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            symbols = root / "symbols.json"
            proposal = root / "proposal.json"
            symbols.write_text(json.dumps({"symbols": []}), encoding="utf-8")
            proposal.write_text(json.dumps({
                "kind": "invariant",
                "body": {
                    "kind": "temporal",
                    "operator": "globally",
                    "operand": {"kind": "literal", "type": "bool", "value": True},
                },
            }), encoding="utf-8")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                exit_code = main([
                    "xlir-smt-check",
                    "--symbols", str(symbols),
                    "--proposal", str(proposal),
                    "--trace-length", "4",
                ])
            output = json.loads(stream.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(output["solver_result"]["status"], "bounded_unsat")
            self.assertEqual(output["solver_result"]["complete"], True)


if __name__ == "__main__":
    unittest.main()
