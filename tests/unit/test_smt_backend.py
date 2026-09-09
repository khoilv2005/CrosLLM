from __future__ import annotations

import unittest

from crossllm.artifacts import ArtifactSymbol
from crossllm.backends import SMTControl, Z3XLIRBackend
from crossllm.contracts import SearchStatus
from crossllm.xlir import XLIRCompiler


class Z3XLIRBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compiler = XLIRCompiler.from_symbols([
            ArtifactSymbol("sym.source.flag", "Bridge.sol", "flag", "source", "storage", "bool"),
            ArtifactSymbol("sym.destination.flag", "Bridge.sol", "flag", "destination", "storage", "bool"),
            ArtifactSymbol("sym.source.amount", "Bridge.sol", "amount", "source", "storage", "uint256"),
            ArtifactSymbol("sym.source.signed_amount", "Bridge.sol", "signed_amount", "source", "storage", "int256"),
        ])
        self.backend = Z3XLIRBackend()

    def compile(self, body: dict[str, object]):
        result = self.compiler.compile({"kind": "invariant", "body": body})
        self.assertTrue(result.ok, result.diagnostics)
        assert result.invariant is not None
        return result.invariant

    @staticmethod
    def symbol(symbol_id: str, state: str = "post") -> dict[str, str]:
        return {"kind": "symbol", "symbol_id": symbol_id, "state": state}

    def test_proves_tautology_and_finds_counterexample(self) -> None:
        tautology = self.compile({
            "kind": "binary", "operator": "eq",
            "left": self.symbol("sym.source.flag"),
            "right": self.symbol("sym.source.flag"),
        })
        proved = self.backend.check_violation(tautology)
        self.assertEqual(proved.status, SearchStatus.BOUNDED_UNSAT)
        self.assertTrue(proved.complete)

        relation = self.compile({
            "kind": "binary", "operator": "eq",
            "left": self.symbol("sym.source.flag"),
            "right": self.symbol("sym.destination.flag"),
        })
        counterexample = self.backend.check_violation(relation)
        self.assertEqual(counterexample.status, SearchStatus.SAT)
        self.assertTrue(counterexample.complete)
        self.assertEqual(set(counterexample.model), {
            "sym.destination.flag|post|destination",
            "sym.source.flag|post|source",
        })

    def test_antecedent_query_and_cancellation_are_explicit(self) -> None:
        implication = self.compile({
            "kind": "binary", "operator": "implies",
            "left": self.symbol("sym.source.flag"),
            "right": self.symbol("sym.destination.flag"),
        })
        antecedent = self.backend.check_antecedent(implication)
        self.assertEqual(antecedent.status, SearchStatus.SAT)

        cancelled = self.backend.check_violation(implication, cancelled=lambda: True)
        self.assertEqual(cancelled.status, SearchStatus.UNKNOWN)
        self.assertFalse(cancelled.complete)
        self.assertEqual(cancelled.reason, "cancelled")

    def test_antecedent_rejects_non_implication_and_hash_is_stable(self) -> None:
        invariant = self.compile({
            "kind": "binary", "operator": "eq",
            "left": self.symbol("sym.source.flag"),
            "right": self.symbol("sym.source.flag"),
        })
        first = self.backend.check_violation(invariant, control=SMTControl(1.0))
        second = self.backend.check_violation(invariant, control=SMTControl(1.0))
        unsupported = self.backend.check_antecedent(invariant)
        self.assertEqual(first.query_hash, second.query_hash)
        self.assertEqual(first.solver, second.solver)
        self.assertEqual(unsupported.status, SearchStatus.UNSUPPORTED)
        self.assertFalse(unsupported.complete)

    def test_prior_campaign_work_exhausts_smt_budget(self) -> None:
        invariant = self.compile({
            "kind": "binary", "operator": "eq",
            "left": self.symbol("sym.source.flag"),
            "right": self.symbol("sym.source.flag"),
        })
        result = self.backend.check_violation(
            invariant,
            control=SMTControl(
                timeout_seconds=10.0,
                campaign_deadline_seconds=10.0,
                campaign_elapsed_seconds=10.0,
            ),
        )
        self.assertEqual(result.status, SearchStatus.TIMEOUT)
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, "campaign_deadline")

    def test_uint256_addition_does_not_wrap_through_overflow(self) -> None:
        invariant = self.compile({
            "kind": "binary", "operator": "neq",
            "left": {
                "kind": "binary", "operator": "add",
                "left": self.symbol("sym.source.amount"),
                "right": {"kind": "literal", "type": "uint256", "value": 1},
            },
            "right": {"kind": "literal", "type": "uint256", "value": 0},
        })
        result = self.backend.check_violation(invariant)
        self.assertEqual(result.status, SearchStatus.BOUNDED_UNSAT)

    def test_int256_ordering_is_signed_and_arithmetic_is_checked(self) -> None:
        ordering = self.compile({
            "kind": "binary",
            "operator": "lt",
            "left": {"kind": "literal", "type": "int256", "value": -1},
            "right": {"kind": "literal", "type": "int256", "value": 0},
        })
        result = self.backend.check_violation(ordering)
        self.assertEqual(result.status, SearchStatus.BOUNDED_UNSAT)

        for operator, left, right in (("add", 2**255 - 1, 1), ("sub", -(2**255), 1)):
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
            checked = self.backend.check_violation(overflowing)
            self.assertEqual(checked.status, SearchStatus.BOUNDED_UNSAT)

    def test_extended_arithmetic_and_bitvector_operators_lower_to_checked_smt(self) -> None:
        def invariant(operator: str, value_type: str, left: int, right: int, expected: int) -> object:
            result = self.compiler.compile({
                "kind": "invariant",
                "body": {
                    "kind": "binary", "operator": "eq",
                    "left": {
                        "kind": "binary", "operator": operator,
                        "left": {"kind": "literal", "type": value_type, "value": left},
                        "right": {"kind": "literal", "type": "uint256" if operator in {"shl", "shr", "sar"} else value_type, "value": right},
                    },
                    "right": {"kind": "literal", "type": value_type, "value": expected},
                },
            })
            self.assertTrue(result.ok, result.diagnostics)
            assert result.invariant is not None
            return result.invariant

        checks = (
            ("mul", "uint256", 6, 7, 42),
            ("div", "int256", -7, 2, -3),
            ("mod", "int256", -7, 2, -1),
            ("band", "uint256", 6, 3, 2),
            ("bor", "uint256", 4, 1, 5),
            ("bxor", "uint256", 7, 3, 4),
            ("shl", "uint256", 1, 3, 8),
            ("shr", "uint256", 8, 2, 2),
            ("sar", "int256", -8, 2, -2),
        )
        for operator, value_type, left, right, expected in checks:
            result = self.backend.check_violation(invariant(operator, value_type, left, right, expected))
            self.assertEqual(result.status, SearchStatus.BOUNDED_UNSAT, operator)

        negation = self.compiler.compile({
            "kind": "invariant", "body": {
                "kind": "binary", "operator": "eq",
                "left": {"kind": "unary", "operator": "neg", "operand": {"kind": "literal", "type": "int256", "value": -3}},
                "right": {"kind": "literal", "type": "int256", "value": 3},
            },
        })
        self.assertTrue(negation.ok, negation.diagnostics)
        assert negation.invariant is not None
        self.assertEqual(self.backend.check_violation(negation.invariant).status, SearchStatus.BOUNDED_UNSAT)

    def test_finite_temporal_and_quantifier_queries_are_explicitly_encoded(self) -> None:
        temporal = self.compile({
            "kind": "temporal",
            "operator": "globally",
            "operand": {"kind": "literal", "type": "bool", "value": True},
        })
        result = self.backend.check_violation(temporal, trace_length=3)
        self.assertEqual(result.status, SearchStatus.BOUNDED_UNSAT)
        self.assertTrue(result.complete)
        quantifier = self.compile({
            "kind": "quantifier",
            "operator": "exists",
            "variable": "value",
            "variable_type": "uint256",
            "domain": [
                {"kind": "literal", "type": "uint256", "value": 0},
                {"kind": "literal", "type": "uint256", "value": 2},
            ],
            "body": {
                "kind": "binary",
                "operator": "eq",
                "left": {"kind": "bound", "variable": "value", "type": "uint256"},
                "right": {"kind": "literal", "type": "uint256", "value": 2},
            },
        })
        quant_result = self.backend.check_violation(quantifier)
        self.assertEqual(quant_result.status, SearchStatus.BOUNDED_UNSAT)
        missing = self.backend.check_violation(temporal)
        self.assertEqual(missing.status, SearchStatus.UNSUPPORTED)
        self.assertEqual(missing.reason, "trace_length_required")
        self.assertTrue(result.complete)


if __name__ == "__main__":
    unittest.main()
