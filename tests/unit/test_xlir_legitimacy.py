from __future__ import annotations

import unittest

from crossllm.artifacts import ArtifactSymbol
from crossllm.xlir import (
    LegitimacyStatus,
    VacuityStatus,
    XLIRCompiler,
    assess_legitimacy,
    check_antecedent_transition,
)


class XLIRLegitimacyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compiler = XLIRCompiler.from_symbols([
            ArtifactSymbol("source.authorized", "Bridge.sol", "authorized", "source", "storage", "bool"),
            ArtifactSymbol("destination.executed", "Bridge.sol", "executed", "destination", "storage", "bool"),
        ])

    def compile(self, body: dict[str, object]):
        result = self.compiler.compile({"kind": "invariant", "body": body})
        self.assertTrue(result.ok, result.diagnostics)
        assert result.invariant is not None
        return result.invariant

    @staticmethod
    def symbol(symbol_id: str, state: str) -> dict[str, str]:
        return {"kind": "symbol", "symbol_id": symbol_id, "state": state}

    def test_legitimacy_is_structural_and_does_not_claim_security_validity(self) -> None:
        invariant = self.compile({
            "kind": "binary", "operator": "implies",
            "left": self.symbol("source.authorized", "pre"),
            "right": self.symbol("destination.executed", "post"),
        })
        result = assess_legitimacy(invariant)
        self.assertEqual(result.status, LegitimacyStatus.ELIGIBLE)
        self.assertTrue(result.cross_domain_relation)
        self.assertTrue(result.transition_relevant)
        self.assertEqual(result.security_validity, "not_assessed")

    def test_legitimacy_rejects_single_domain_or_single_state_properties(self) -> None:
        single_domain = self.compile({
            "kind": "binary", "operator": "eq",
            "left": self.symbol("source.authorized", "pre"),
            "right": {"kind": "literal", "type": "bool", "value": True},
        })
        result = assess_legitimacy(single_domain)
        self.assertEqual(result.status, LegitimacyStatus.UNWARRANTED)
        self.assertEqual(result.reason, "missing_required_domain")

        relaxed = assess_legitimacy(single_domain, required_domains=("source",), required_states=("pre",))
        self.assertEqual(relaxed.status, LegitimacyStatus.ELIGIBLE)

    def test_transition_vacuity_requires_complete_transition_trace_space(self) -> None:
        invariant = self.compile({
            "kind": "binary", "operator": "implies",
            "left": self.symbol("source.authorized", "pre"),
            "right": self.symbol("destination.executed", "post"),
        })
        key_source = ("source.authorized", "pre", "source")
        key_destination = ("destination.executed", "post", "destination")
        false_traces = [
            [{key_source: False, key_destination: False}],
            [{key_source: False, key_destination: True}],
        ]
        complete = check_antecedent_transition(
            invariant, false_traces, exhaustive=True, transition_complete=True
        )
        self.assertEqual(complete.status, VacuityStatus.BOUNDED_UNSAT)
        self.assertTrue(complete.complete)

        incomplete = check_antecedent_transition(
            invariant, false_traces, exhaustive=True, transition_complete=False
        )
        self.assertEqual(incomplete.status, VacuityStatus.UNKNOWN)
        self.assertFalse(incomplete.complete)

    def test_transition_vacuity_keeps_reachability_errors_and_empty_space_unknown(self) -> None:
        invariant = self.compile({
            "kind": "binary", "operator": "implies",
            "left": self.symbol("source.authorized", "pre"),
            "right": self.symbol("destination.executed", "post"),
        })
        key_source = ("source.authorized", "pre", "source")
        key_destination = ("destination.executed", "post", "destination")
        reachable = check_antecedent_transition(
            invariant,
            [[{key_source: True, key_destination: False}]],
            exhaustive=True,
            transition_complete=True,
        )
        self.assertEqual(reachable.status, VacuityStatus.REACHABLE)

        error = check_antecedent_transition(
            invariant,
            [[{key_destination: False}]],
            exhaustive=True,
            transition_complete=True,
        )
        self.assertEqual(error.status, VacuityStatus.UNKNOWN)
        self.assertIn("transition_trace_error", error.reason or "")

        empty = check_antecedent_transition(
            invariant, [], exhaustive=True, transition_complete=True
        )
        self.assertEqual(empty.status, VacuityStatus.UNKNOWN)
        self.assertFalse(empty.complete)


if __name__ == "__main__":
    unittest.main()
