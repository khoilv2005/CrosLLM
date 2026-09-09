from __future__ import annotations

import unittest

from crossllm.artifacts import ArtifactSymbol
from crossllm.xlir import EvaluationError, XLIRCompiler, evaluate_expression, evaluate_invariant, evaluate_trace


class XLIREvaluatorTests(unittest.TestCase):
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

    def test_evaluates_pre_post_bindings_and_short_circuits(self) -> None:
        invariant = self.compile(
            {
                "kind": "binary",
                "operator": "and",
                "left": {"kind": "symbol", "symbol_id": "sym.destination.executed", "state": "post"},
                "right": {
                    "kind": "binary",
                    "operator": "eq",
                    "left": {"kind": "symbol", "symbol_id": "sym.source.amount", "state": "pre"},
                    "right": {"kind": "literal", "type": "uint256", "value": 7},
                },
            }
        )
        self.assertTrue(
            evaluate_invariant(
                invariant,
                {
                    ("sym.destination.executed", "post", "destination"): True,
                    ("sym.source.amount", "pre", "source"): 7,
                },
            )
        )

    def test_missing_or_cross_domain_binding_is_rejected(self) -> None:
        invariant = self.compile(
            {
                "kind": "binary",
                "operator": "eq",
                "left": {"kind": "symbol", "symbol_id": "sym.source.amount", "state": "pre"},
                "right": {"kind": "literal", "type": "uint256", "value": 0},
            }
        )
        with self.assertRaisesRegex(EvaluationError, "missing binding"):
            evaluate_invariant(invariant, {("sym.source.amount", "post", "source"): 0})

    def test_uint256_underflow_is_not_silently_wrapped(self) -> None:
        invariant = self.compile(
            {
                "kind": "binary",
                "operator": "eq",
                "left": {
                    "kind": "binary",
                    "operator": "sub",
                    "left": {"kind": "literal", "type": "uint256", "value": 0},
                    "right": {"kind": "literal", "type": "uint256", "value": 1},
                },
                "right": {"kind": "literal", "type": "uint256", "value": 0},
            }
        )
        with self.assertRaisesRegex(EvaluationError, "underflow"):
            evaluate_invariant(invariant, {})

    def test_int256_uses_signed_ordering_and_rejects_overflow(self) -> None:
        ordering = self.compile({
            "kind": "binary",
            "operator": "lt",
            "left": {"kind": "literal", "type": "int256", "value": -1},
            "right": {"kind": "literal", "type": "int256", "value": 0},
        })
        self.assertTrue(evaluate_invariant(ordering, {}))
        for operator, left, right, message in (
            ("add", 2**255 - 1, 1, "addition overflow"),
            ("sub", -(2**255), 1, "subtraction overflow"),
        ):
            overflowing = self.compile({
                "kind": "binary",
                "operator": "eq",
                "left": {
                    "kind": "binary",
                    "operator": operator,
                    "left": {"kind": "literal", "type": "int256", "value": left},
                    "right": {"kind": "literal", "type": "int256", "value": right},
                },
                "right": {"kind": "literal", "type": "int256", "value": 0},
            })
            with self.assertRaisesRegex(EvaluationError, message):
                evaluate_invariant(overflowing, {})

    def test_extended_arithmetic_bitwise_and_shift_semantics(self) -> None:
        def evaluate(operator: str, value_type: str, left: int, expected: int, right: int | None = None) -> bool:
            body: dict[str, object]
            left_expr = {"kind": "literal", "type": value_type, "value": left}
            if right is None:
                body = {"kind": "unary", "operator": operator, "operand": left_expr}
            else:
                body = {
                    "kind": "binary", "operator": operator,
                    "left": left_expr,
                    "right": {"kind": "literal", "type": "uint256" if operator in {"shl", "shr", "sar"} else value_type, "value": right},
                }
            comparison_type = value_type
            invariant = self.compile({
                "kind": "binary", "operator": "eq",
                "left": body,
                "right": {"kind": "literal", "type": comparison_type, "value": expected},
            })
            return evaluate_invariant(invariant, {})

        self.assertTrue(evaluate("mul", "uint256", 6, 42, 7))
        self.assertTrue(evaluate("div", "int256", -7, -3, 2))
        self.assertTrue(evaluate("mod", "int256", -7, -1, 2))
        self.assertTrue(evaluate("band", "uint256", 6, 2, 3))
        self.assertTrue(evaluate("bor", "uint256", 4, 5, 1))
        self.assertTrue(evaluate("bxor", "uint256", 7, 4, 3))
        self.assertTrue(evaluate("shl", "uint256", 1, 8, 3))
        self.assertTrue(evaluate("shr", "uint256", 8, 2, 2))
        self.assertTrue(evaluate("sar", "int256", -8, -2, 2))
        self.assertTrue(evaluate("bitnot", "int256", 0, -1))

        zero_division = self.compile({
            "kind": "binary", "operator": "eq",
            "left": {
                "kind": "binary", "operator": "div",
                "left": {"kind": "literal", "type": "uint256", "value": 1},
                "right": {"kind": "literal", "type": "uint256", "value": 0},
            },
            "right": {"kind": "literal", "type": "uint256", "value": 0},
        })
        with self.assertRaisesRegex(EvaluationError, "division by zero"):
            evaluate_invariant(zero_division, {})

        overflowing = self.compile({
            "kind": "binary", "operator": "eq",
            "left": {
                "kind": "binary", "operator": "mul",
                "left": {"kind": "literal", "type": "uint256", "value": 2**255},
                "right": {"kind": "literal", "type": "uint256", "value": 2},
            },
            "right": {"kind": "literal", "type": "uint256", "value": 0},
        })
        with self.assertRaisesRegex(EvaluationError, "multiplication overflow"):
            evaluate_invariant(overflowing, {})

    def test_finite_quantifier_and_temporal_trace_semantics(self) -> None:
        quantified = self.compile({
            "kind": "quantifier",
            "operator": "exists",
            "variable": "nonce",
            "variable_type": "uint256",
            "domain": [
                {"kind": "literal", "type": "uint256", "value": 0},
                {"kind": "literal", "type": "uint256", "value": 7},
            ],
            "body": {
                "kind": "binary",
                "operator": "eq",
                "left": {"kind": "bound", "variable": "nonce", "type": "uint256"},
                "right": {"kind": "literal", "type": "uint256", "value": 7},
            },
        })
        self.assertTrue(evaluate_invariant(quantified, {}))
        temporal = self.compile({
            "kind": "temporal",
            "operator": "globally",
            "operand": {
                "kind": "symbol",
                "symbol_id": "sym.destination.executed",
                "state": "post",
            },
        })
        key = ("sym.destination.executed", "post", "destination")
        self.assertTrue(evaluate_trace(temporal, [{key: True}, {key: True}]))
        self.assertFalse(evaluate_trace(temporal, [{key: True}, {key: False}]))
        once_result = XLIRCompiler.from_symbols(self.symbols).compile({
            "kind": "invariant",
            "body": {
                "kind": "temporal",
                "operator": "once",
                "horizon": 1,
                "operand": {
                    "kind": "symbol",
                    "symbol_id": "sym.destination.executed",
                    "state": "post",
                },
            },
        })
        self.assertTrue(once_result.ok)
        assert once_result.invariant is not None
        self.assertTrue(
            evaluate_expression(
                once_result.invariant.body,
                {key: True},
                trace=[{key: False}, {key: True}],
                index=1,
            )
        )
        self.assertTrue(
            evaluate_trace(once_result.invariant, [{key: False}, {key: False}, {key: True}])
            is False
        )


if __name__ == "__main__":
    unittest.main()
