from __future__ import annotations

import unittest
import contextlib
import io
import json
import tempfile
from pathlib import Path

from crossllm.artifacts import ArtifactSymbol
from crossllm.cli import main
from crossllm.xlir import XLIRCompiler


class XLIRCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compiler = XLIRCompiler.from_symbols([
            ArtifactSymbol("sym.source.amount", "Bridge.sol", "amount", "source", "storage", "uint256"),
            ArtifactSymbol("sym.destination.amount", "Bridge.sol", "amount", "destination", "storage", "uint256"),
            ArtifactSymbol("sym.destination.executed", "Bridge.sol", "executed", "destination", "storage", "bool"),
        ])

    def test_compiles_grounded_typed_invariant_deterministically(self) -> None:
        payload = {
            "kind": "invariant",
            "invariant_id": "value-conservation",
            "body": {
                "kind": "binary", "operator": "eq",
                "left": {"kind": "symbol", "symbol_id": "sym.source.amount", "state": "post"},
                "right": {"kind": "symbol", "symbol_id": "sym.destination.amount", "state": "post"},
            },
        }
        first = self.compiler.compile(payload)
        second = self.compiler.compile(payload)
        self.assertTrue(first.ok)
        self.assertEqual(first.invariant.canonical_hash, second.invariant.canonical_hash)
        self.assertEqual(first.invariant.node_count, 3)

    def test_rejects_unresolved_symbol_and_type_mismatch(self) -> None:
        unresolved = self.compiler.compile({
            "kind": "invariant",
            "body": {"kind": "symbol", "symbol_id": "sym.missing", "state": "post"},
        })
        self.assertEqual(unresolved.diagnostics[0].code, "unresolved_symbol")
        mismatch = self.compiler.compile({
            "kind": "invariant",
            "body": {
                "kind": "binary", "operator": "eq",
                "left": {"kind": "symbol", "symbol_id": "sym.source.amount", "state": "post"},
                "right": {"kind": "symbol", "symbol_id": "sym.destination.executed", "state": "post"},
            },
        })
        self.assertEqual(mismatch.diagnostics[0].code, "type_mismatch")

    def test_rejects_non_boolean_root_and_respects_ast_limit(self) -> None:
        root = self.compiler.compile({
            "kind": "invariant",
            "body": {"kind": "symbol", "symbol_id": "sym.source.amount", "state": "post"},
        })
        self.assertEqual(root.diagnostics[0].code, "non_boolean_root")
        limited = XLIRCompiler.from_symbols([], maximum_ast_nodes=1).compile({
            "kind": "invariant",
            "body": {
                "kind": "unary", "operator": "not",
                "operand": {"kind": "literal", "type": "bool", "value": True},
            },
        })
        self.assertEqual(limited.diagnostics[0].code, "ast_limit")

    def test_abstain_is_explicit_and_requires_reason(self) -> None:
        valid = self.compiler.compile({"abstain": True, "reason": "No grounded property"})
        self.assertTrue(valid.abstained)
        self.assertFalse(valid.diagnostics)
        invalid = self.compiler.compile({"abstain": True})
        self.assertEqual(invalid.diagnostics[0].code, "missing_reason")

    def test_malformed_json_values_return_diagnostics_instead_of_escaping(self) -> None:
        malformed = [
            {"kind": [], "body": {"kind": "literal", "type": "bool", "value": True}},
            {"kind": "invariant", "body": {"kind": "literal", "type": [], "value": True}},
            {
                "kind": "invariant",
                "body": {
                    "kind": "binary", "operator": [],
                    "left": {"kind": "literal", "type": "bool", "value": True},
                    "right": {"kind": "literal", "type": "bool", "value": True},
                },
            },
        ]
        expected_codes = ("invalid_kind", "invalid_literal_type", "malformed_payload")
        for payload, expected_code in zip(malformed, expected_codes):
            result = self.compiler.compile(payload)
            self.assertFalse(result.ok)
            self.assertEqual(result.diagnostics[0].code, expected_code)

    def test_primitive_macro_expands_to_the_same_typed_core(self) -> None:
        primitive = self.compiler.compile({
            "kind": "invariant",
            "body": {
                "kind": "primitive",
                "primitive_id": "justified_destination_effect",
                "arguments": [
                    {"kind": "symbol", "symbol_id": "sym.destination.executed", "state": "pre"},
                    {"kind": "symbol", "symbol_id": "sym.destination.executed", "state": "post"},
                ],
            },
        })
        core = self.compiler.compile({
            "kind": "invariant",
            "body": {
                "kind": "binary", "operator": "implies",
                "left": {"kind": "symbol", "symbol_id": "sym.destination.executed", "state": "pre"},
                "right": {"kind": "symbol", "symbol_id": "sym.destination.executed", "state": "post"},
            },
        })
        self.assertTrue(primitive.ok)
        self.assertTrue(core.ok)
        self.assertEqual(primitive.invariant.canonical_hash, core.invariant.canonical_hash)

    def test_unknown_or_wrong_arity_primitive_is_rejected(self) -> None:
        result = self.compiler.compile({
            "kind": "invariant",
            "body": {"kind": "primitive", "primitive_id": "replay_exclusion", "arguments": []},
        })
        self.assertEqual(result.diagnostics[0].code, "invalid_primitive")

    def test_finite_quantifier_and_temporal_core_are_typed(self) -> None:
        quantified = self.compiler.compile({
            "kind": "invariant",
            "body": {
                "kind": "quantifier",
                "operator": "forall",
                "variable": "nonce",
                "variable_type": "uint256",
                "domain": [
                    {"kind": "literal", "type": "uint256", "value": 0},
                    {"kind": "literal", "type": "uint256", "value": 1},
                ],
                "body": {
                    "kind": "binary",
                    "operator": "eq",
                    "left": {"kind": "bound", "variable": "nonce", "type": "uint256"},
                    "right": {"kind": "bound", "variable": "nonce", "type": "uint256"},
                },
            },
        })
        self.assertTrue(quantified.ok, quantified.diagnostics)
        self.assertEqual(quantified.invariant.body.value_type.value, "bool")
        temporal = self.compiler.compile({
            "kind": "invariant",
            "body": {
                "kind": "temporal",
                "operator": "once",
                "horizon": 2,
                "operand": {"kind": "literal", "type": "bool", "value": True},
            },
        })
        self.assertTrue(temporal.ok, temporal.diagnostics)

    def test_invalid_temporal_and_unresolved_bound_are_rejected(self) -> None:
        temporal = self.compiler.compile({
            "kind": "invariant",
            "body": {
                "kind": "temporal",
                "operator": "globally",
                "horizon": 1,
                "operand": {"kind": "literal", "type": "bool", "value": True},
            },
        })
        self.assertEqual(temporal.diagnostics[0].code, "unexpected_temporal_horizon")
        bound = self.compiler.compile({
            "kind": "invariant",
            "body": {
                "kind": "binary",
                "operator": "eq",
                "left": {"kind": "bound", "variable": "missing", "type": "uint256"},
                "right": {"kind": "literal", "type": "uint256", "value": 0},
            },
        })
        self.assertEqual(bound.diagnostics[0].code, "unresolved_bound_variable")

    def test_invalid_hex_address_and_bytes32_literals_are_rejected(self) -> None:
        for value_type, value in (
            ("address", "0x" + "g" * 40),
            ("bytes32", "0x" + "z" * 64),
        ):
            result = self.compiler.compile({
                "kind": "invariant",
                "body": {
                    "kind": "binary",
                    "operator": "eq",
                    "left": {"kind": "literal", "type": value_type, "value": value},
                    "right": {"kind": "literal", "type": value_type, "value": value},
                },
            })
            self.assertEqual(result.diagnostics[0].code, "invalid_literal")

    def test_int256_literals_and_arithmetic_are_typed_and_range_checked(self) -> None:
        valid = self.compiler.compile({
            "kind": "invariant",
            "body": {
                "kind": "binary",
                "operator": "lt",
                "left": {
                    "kind": "binary",
                    "operator": "add",
                    "left": {"kind": "literal", "type": "int256", "value": -2},
                    "right": {"kind": "literal", "type": "int256", "value": 1},
                },
                "right": {"kind": "literal", "type": "int256", "value": 0},
            },
        })
        self.assertTrue(valid.ok, valid.diagnostics)
        self.assertEqual(valid.invariant.body.left.value_type.value, "int256")
        for value in (-(2**255) - 1, 2**255):
            invalid = self.compiler.compile({
                "kind": "invariant",
                "body": {
                    "kind": "binary",
                    "operator": "eq",
                    "left": {"kind": "literal", "type": "int256", "value": value},
                    "right": {"kind": "literal", "type": "int256", "value": 0},
                },
            })
            self.assertEqual(invalid.diagnostics[0].code, "invalid_literal")

    def test_extended_integer_and_bitvector_operators_are_typed(self) -> None:
        valid_bodies = [
            {"kind": "unary", "operator": "neg", "operand": {"kind": "literal", "type": "int256", "value": -1}},
            {"kind": "unary", "operator": "bitnot", "operand": {"kind": "literal", "type": "uint256", "value": 0}},
            {
                "kind": "binary", "operator": "mul",
                "left": {"kind": "literal", "type": "uint256", "value": 2},
                "right": {"kind": "literal", "type": "uint256", "value": 3},
            },
            {
                "kind": "binary", "operator": "div",
                "left": {"kind": "literal", "type": "int256", "value": -7},
                "right": {"kind": "literal", "type": "int256", "value": 2},
            },
            {
                "kind": "binary", "operator": "band",
                "left": {"kind": "literal", "type": "uint256", "value": 6},
                "right": {"kind": "literal", "type": "uint256", "value": 3},
            },
            {
                "kind": "binary", "operator": "sar",
                "left": {"kind": "literal", "type": "int256", "value": -4},
                "right": {"kind": "literal", "type": "uint256", "value": 1},
            },
        ]
        for body in valid_bodies:
            result = self.compiler.compile({"kind": "invariant", "body": {"kind": "binary", "operator": "eq", "left": body, "right": body}})
            self.assertTrue(result.ok, (body, result.diagnostics))

        invalid_bodies = [
            {"kind": "unary", "operator": "neg", "operand": {"kind": "literal", "type": "uint256", "value": 1}},
            {
                "kind": "binary", "operator": "sar",
                "left": {"kind": "literal", "type": "uint256", "value": 1},
                "right": {"kind": "literal", "type": "uint256", "value": 1},
            },
            {
                "kind": "binary", "operator": "shl",
                "left": {"kind": "literal", "type": "uint256", "value": 1},
                "right": {"kind": "literal", "type": "int256", "value": 1},
            },
        ]
        for body in invalid_bodies:
            result = self.compiler.compile({"kind": "invariant", "body": {"kind": "binary", "operator": "eq", "left": body, "right": body}})
            self.assertEqual(result.diagnostics[0].code, "type_mismatch")

    def test_quantifier_domain_counts_toward_ast_limit(self) -> None:
        limited = XLIRCompiler.from_symbols([], maximum_ast_nodes=2).compile({
            "kind": "invariant",
            "body": {
                "kind": "quantifier",
                "operator": "forall",
                "variable": "x",
                "variable_type": "uint256",
                "domain": [
                    {"kind": "literal", "type": "uint256", "value": 0},
                    {"kind": "literal", "type": "uint256", "value": 1},
                ],
                "body": {"kind": "literal", "type": "bool", "value": True},
            },
        })
        self.assertEqual(limited.diagnostics[0].code, "ast_limit")

    def test_cli_emits_grounded_invariant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            symbols = root / "symbols.json"
            proposal = root / "proposal.json"
            symbols.write_text(json.dumps({"symbols": [
                {"symbol_id": "sym.flag", "path": "Bridge.sol", "name": "flag", "domain": "source", "kind": "storage", "type": "bool"}
            ]}), encoding="utf-8")
            proposal.write_text(json.dumps({
                "kind": "invariant",
                "body": {"kind": "symbol", "symbol_id": "sym.flag", "state": "post"},
            }), encoding="utf-8")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                exit_code = main(["xlir-validate", "--symbols", str(symbols), "--proposal", str(proposal)])
            result = json.loads(stream.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(result["ok"])
            self.assertEqual(result["invariant"]["body"]["symbol_id"], "sym.flag")

    def test_cli_accepts_windows_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            symbols = root / "symbols.json"
            proposal = root / "proposal.json"
            symbols.write_text(json.dumps({"symbols": []}), encoding="utf-8-sig")
            proposal.write_text(json.dumps({"abstain": True, "reason": "No symbols"}), encoding="utf-8-sig")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                exit_code = main(["xlir-validate", "--symbols", str(symbols), "--proposal", str(proposal)])
            self.assertEqual(exit_code, 0)
            self.assertTrue(json.loads(stream.getvalue())["abstained"])


if __name__ == "__main__":
    unittest.main()
