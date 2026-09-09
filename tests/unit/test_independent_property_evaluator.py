from __future__ import annotations

import json
import dataclasses
from pathlib import Path
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from crossllm.artifacts import ArtifactSymbol
from crossllm.contracts import ReplayStatus
from crossllm.replay import IndependentPropertyEvaluator, PropertyEvaluatorSpec, SourceObservation
from crossllm.xlir import XLIRCompiler


ROOT = Path(__file__).resolve().parents[2]


class IndependentPropertyEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        symbol = ArtifactSymbol("sym.destination.executed", "Bridge.sol", "executed", "destination", "storage", "bool")
        compiled = XLIRCompiler.from_symbols([symbol]).compile({
            "kind": "invariant",
            "body": {"kind": "symbol", "symbol_id": symbol.symbol_id, "state": "post"},
        })
        self.assertTrue(compiled.ok, compiled.diagnostics)
        assert compiled.invariant is not None
        self.invariant = compiled.invariant
        self.key = (symbol.symbol_id, "post", "destination")
        self.spec = PropertyEvaluatorSpec(
            evaluator_id="crossllm-concrete-xlir-evaluator",
            evaluator_revision="development-1",
            artifact_hash="a" * 64,
            initialization_hash="b" * 64,
            profile_hash="c" * 64,
            semantic_engine="concrete-xlir-v1",
        )

    def observation(self, value: bool) -> SourceObservation:
        return SourceObservation("obs-1", "d" * 64, {self.key: value})

    def test_pass_fail_and_unknown_are_distinct_and_do_not_call_smt_lowering(self) -> None:
        evaluator = IndependentPropertyEvaluator()
        with patch("crossllm.xlir.lowering.XLIRLowerer.lower", side_effect=AssertionError("SMT lowerer called")):
            passed = evaluator.evaluate(self.spec, self.invariant, self.observation(True))
            failed = evaluator.evaluate(self.spec, self.invariant, self.observation(False))
            unknown = evaluator.evaluate(self.spec, self.invariant, SourceObservation("obs-2", "e" * 64, {}))
        self.assertEqual(passed.status, ReplayStatus.PASS)
        self.assertTrue(passed.property_holds)
        self.assertEqual(failed.status, ReplayStatus.FAIL)
        self.assertFalse(failed.property_holds)
        self.assertEqual(unknown.status, ReplayStatus.UNKNOWN)
        self.assertIsNone(unknown.property_holds)
        self.assertEqual(passed.security_relevance, "unassessed")

    def test_spec_and_observation_hashes_are_bound_and_result_matches_schema(self) -> None:
        result = IndependentPropertyEvaluator().evaluate(self.spec, self.invariant, self.observation(True))
        schema = json.loads((ROOT / "schemas/source_property_evaluation.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(result.as_dict())), [])
        self.assertEqual(result.evaluator_spec_hash, self.spec.spec_hash)
        self.assertEqual(result.observation_hash, self.observation(True).observation_hash)
        self.assertEqual(len(result.property_hash), 64)

    def test_invalid_identity_and_binding_key_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "trace_hash"):
            SourceObservation("obs", "not-a-hash", {})
        with self.assertRaisesRegex(ValueError, "binding keys"):
            SourceObservation("obs", "d" * 64, {"wrong": True})  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "artifact_hash"):
            PropertyEvaluatorSpec("evaluator", "r1", "not-a-hash", "b" * 64, "c" * 64, "engine")

    def test_tampered_invariant_hash_is_unknown_not_a_property_result(self) -> None:
        tampered = dataclasses.replace(self.invariant, canonical_hash="0" * 64)
        result = IndependentPropertyEvaluator().evaluate(self.spec, tampered, self.observation(True))
        self.assertEqual(result.status, ReplayStatus.UNKNOWN)
        self.assertIsNone(result.property_holds)
        self.assertEqual(result.reason, "invariant_canonical_hash_mismatch")


if __name__ == "__main__":
    unittest.main()
