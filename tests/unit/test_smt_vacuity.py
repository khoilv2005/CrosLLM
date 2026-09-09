from __future__ import annotations

import unittest

from crossllm.artifacts import ArtifactSymbol
from crossllm.xlir import (
    XLIRCompiler,
    VacuityStatus,
    check_antecedent_smt,
)


class SMTVacuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compiler = XLIRCompiler.from_symbols([
            ArtifactSymbol("sym.source.flag", "Bridge.sol", "flag", "source", "storage", "bool"),
        ])

    def compile(self, body: dict[str, object]):
        result = self.compiler.compile({"kind": "invariant", "body": body})
        self.assertTrue(result.ok, result.diagnostics)
        assert result.invariant is not None
        return result.invariant

    @staticmethod
    def symbol() -> dict[str, str]:
        return {"kind": "symbol", "symbol_id": "sym.source.flag", "state": "post"}

    def test_solver_vacuity_preserves_reachable_and_bounded_unsat(self) -> None:
        reachable = self.compile({
            "kind": "binary", "operator": "implies",
            "left": self.symbol(),
            "right": {"kind": "literal", "type": "bool", "value": True},
        })
        reachable_result = check_antecedent_smt(reachable)
        self.assertEqual(reachable_result.status, VacuityStatus.REACHABLE)
        self.assertTrue(reachable_result.complete)

        impossible = self.compile({
            "kind": "binary", "operator": "implies",
            "left": {
                "kind": "binary", "operator": "and",
                "left": self.symbol(),
                "right": {"kind": "unary", "operator": "not", "operand": self.symbol()},
            },
            "right": {"kind": "literal", "type": "bool", "value": True},
        })
        impossible_result = check_antecedent_smt(impossible)
        self.assertEqual(impossible_result.status, VacuityStatus.BOUNDED_UNSAT)
        self.assertTrue(impossible_result.complete)

    def test_solver_vacuity_keeps_operational_unknown_and_non_implication(self) -> None:
        implication = self.compile({
            "kind": "binary", "operator": "implies",
            "left": self.symbol(),
            "right": {"kind": "literal", "type": "bool", "value": True},
        })
        cancelled = check_antecedent_smt(implication, cancelled=lambda: True)
        self.assertEqual(cancelled.status, VacuityStatus.UNKNOWN)
        self.assertFalse(cancelled.complete)
        self.assertIn("solver_unknown", cancelled.reason or "")

        non_implication = self.compile({
            "kind": "binary", "operator": "eq",
            "left": self.symbol(),
            "right": self.symbol(),
        })
        not_applicable = check_antecedent_smt(non_implication)
        self.assertEqual(not_applicable.status, VacuityStatus.NOT_APPLICABLE)
        self.assertTrue(not_applicable.complete)


if __name__ == "__main__":
    unittest.main()
