from __future__ import annotations

import unittest

from crossllm.artifacts import ArtifactSymbol
from crossllm.xlir import (
    VacuityStatus,
    XLIRCompiler,
    XLIRLowerer,
    check_antecedent,
)


class XLIRLoweringVacuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.symbols = [
            ArtifactSymbol("sym.source.amount", "Bridge.sol", "amount", "source", "storage", "uint256"),
            ArtifactSymbol("sym.destination.executed", "Bridge.sol", "executed", "destination", "storage", "bool"),
        ]

    def compile(self, body: dict[str, object]):
        result = XLIRCompiler.from_symbols(self.symbols).compile({"kind": "invariant", "body": body})
        self.assertTrue(result.ok, result.diagnostics)
        assert result.invariant is not None
        return result.invariant

    def test_lowering_is_typed_deterministic_and_source_mapped(self) -> None:
        invariant = self.compile(
            {
                "kind": "binary",
                "operator": "implies",
                "left": {"kind": "symbol", "symbol_id": "sym.destination.executed", "state": "post"},
                "right": {
                    "kind": "binary",
                    "operator": "eq",
                    "left": {"kind": "symbol", "symbol_id": "sym.source.amount", "state": "pre"},
                    "right": {"kind": "literal", "type": "uint256", "value": 3},
                },
            }
        )
        first = XLIRLowerer().lower(invariant)
        second = XLIRLowerer().lower(invariant)
        self.assertTrue(first.ok, first.diagnostics)
        self.assertEqual(first.ir.as_dict(), second.ir.as_dict())
        self.assertEqual(first.ir.root.sort, "Bool")
        self.assertIn("$.body.left", first.ir.source_map.values())
        self.assertIn("bv3 256", first.ir.root.term)

    def test_vacuity_separates_reachable_bounded_unsat_and_unknown(self) -> None:
        invariant = self.compile(
            {
                "kind": "binary",
                "operator": "implies",
                "left": {"kind": "symbol", "symbol_id": "sym.destination.executed", "state": "post"},
                "right": {"kind": "literal", "type": "bool", "value": True},
            }
        )
        key = ("sym.destination.executed", "post", "destination")
        reachable = check_antecedent(invariant, [{key: False}, {key: True}], exhaustive=True)
        self.assertEqual(reachable.status, VacuityStatus.REACHABLE)
        unsat = check_antecedent(invariant, [{key: False}], exhaustive=True)
        self.assertEqual(unsat.status, VacuityStatus.BOUNDED_UNSAT)
        unknown = check_antecedent(invariant, [{key: False}], exhaustive=False)
        self.assertEqual(unknown.status, VacuityStatus.UNKNOWN)

    def test_vacuity_binding_error_is_not_unreachable(self) -> None:
        invariant = self.compile(
            {
                "kind": "binary",
                "operator": "implies",
                "left": {"kind": "symbol", "symbol_id": "sym.destination.executed", "state": "post"},
                "right": {"kind": "literal", "type": "bool", "value": True},
            }
        )
        result = check_antecedent(invariant, [{}], exhaustive=True)
        self.assertEqual(result.status, VacuityStatus.UNKNOWN)

    def test_non_implication_is_not_applicable(self) -> None:
        invariant = self.compile({"kind": "literal", "type": "bool", "value": True})
        result = check_antecedent(invariant, [], exhaustive=True)
        self.assertEqual(result.status, VacuityStatus.NOT_APPLICABLE)

    def test_temporal_lowering_indexes_finite_trace_and_expands_quantifier(self) -> None:
        invariant = self.compile({
            "kind": "temporal",
            "operator": "globally",
            "operand": {
                "kind": "binary",
                "operator": "eq",
                "left": {"kind": "symbol", "symbol_id": "sym.source.amount", "state": "post"},
                "right": {"kind": "literal", "type": "uint256", "value": 3},
            },
        })
        lowered = XLIRLowerer().lower(invariant, trace_length=3)
        self.assertTrue(lowered.ok, lowered.diagnostics)
        assert lowered.ir is not None
        self.assertEqual(lowered.ir.trace_length, 3)
        self.assertIn("(and", lowered.ir.root.term)
        self.assertEqual(len(lowered.ir.symbol_names), 3)
        missing_length = XLIRLowerer().lower(invariant)
        self.assertFalse(missing_length.ok)
        self.assertEqual(missing_length.diagnostics[0].message, "temporal lowering requires trace_length")

        quantified = self.compile({
            "kind": "quantifier",
            "operator": "exists",
            "variable": "nonce",
            "variable_type": "uint256",
            "domain": [
                {"kind": "literal", "type": "uint256", "value": 0},
                {"kind": "literal", "type": "uint256", "value": 3},
            ],
            "body": {
                "kind": "binary",
                "operator": "eq",
                "left": {"kind": "bound", "variable": "nonce", "type": "uint256"},
                "right": {"kind": "literal", "type": "uint256", "value": 3},
            },
        })
        quant_lowered = XLIRLowerer().lower(quantified)
        self.assertTrue(quant_lowered.ok, quant_lowered.diagnostics)
        assert quant_lowered.ir is not None
        self.assertIn("(_ bv3 256)", quant_lowered.ir.root.term)

    def test_int256_lowering_uses_signed_comparison_and_twos_complement_literals(self) -> None:
        invariant = self.compile({
            "kind": "binary",
            "operator": "lt",
            "left": {"kind": "literal", "type": "int256", "value": -1},
            "right": {"kind": "literal", "type": "int256", "value": 0},
        })
        lowered = XLIRLowerer().lower(invariant)
        self.assertTrue(lowered.ok, lowered.diagnostics)
        assert lowered.ir is not None
        self.assertIn("(bvslt", lowered.ir.root.term)
        self.assertIn(f"(_ bv{2**256 - 1} 256)", lowered.ir.root.term)


if __name__ == "__main__":
    unittest.main()
