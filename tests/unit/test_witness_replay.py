from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from crossllm.backends import BoundedPairedExplorer, SymbolicPairedExplorer
from crossllm.contracts import ReplayStatus
from crossllm.replay import NativeReplay, WitnessProjector
from crossllm.semantics import Message, PairedFixture, TransitionBounds


def message(nonce: int) -> Message:
    return Message("source", "destination", "bridge", "receiver", nonce, f"commit-{nonce}")


class WitnessReplayTests(unittest.TestCase):
    def sat_result(self):
        return BoundedPairedExplorer([message(1), message(2)]).search(
            PairedFixture(bounds=TransitionBounds(4, 4, 2)),
            lambda state: bool(state.delivered) and state.delivered[0].nonce == 2 and any(
                pending.nonce == 1 for pending in state.pending
            ),
        )

    def test_projected_witness_replays_and_keeps_independent_unknown(self) -> None:
        fixture = PairedFixture(bounds=TransitionBounds(4, 4, 2))
        witness = WitnessProjector().project(
            self.sat_result(), fixture, witness_id="wit-1", query_id="query-1", created_at="2026-09-08T00:00:00Z"
        )
        self.assertEqual(witness.domains, ("destination", "source"))
        self.assertEqual(witness.independent_replay_status, "unknown")
        replay = NativeReplay().check(witness, fixture)
        self.assertEqual(replay.status, ReplayStatus.PASS)
        self.assertEqual(replay.executed_actions, 3)

    def test_symbolic_sat_witness_uses_the_same_projection_contract(self) -> None:
        fixture = PairedFixture(bounds=TransitionBounds(4, 4, 2))
        result = SymbolicPairedExplorer([message(1), message(2)]).search(
            fixture,
            lambda state: bool(state.delivered) and state.delivered[0].nonce == 2 and any(
                pending.nonce == 1 for pending in state.pending
            ),
        )
        self.assertEqual(result.status.value, "sat")
        witness = WitnessProjector().project(
            result, fixture, witness_id="symbolic-wit", query_id="symbolic-query"
        )
        self.assertEqual(NativeReplay().check(witness, fixture).status, ReplayStatus.PASS)

    def test_wrong_initial_state_and_tampered_trace_are_rejected(self) -> None:
        fixture = PairedFixture(bounds=TransitionBounds(4, 4, 2))
        witness = WitnessProjector().project(self.sat_result(), fixture, witness_id="wit-1", query_id="query-1")
        wrong_hash = dataclasses.replace(witness, initial_state_hash="0" * 64)
        self.assertEqual(NativeReplay().check(wrong_hash, fixture).reason, "initial_state_hash_mismatch")
        tampered = dataclasses.replace(witness, trace_hash="0" * 64)
        self.assertEqual(NativeReplay().check(tampered, fixture).reason, "trace_hash_mismatch")

    def test_non_sat_result_cannot_be_projected(self) -> None:
        result = BoundedPairedExplorer([message(1)]).search(
            PairedFixture(bounds=TransitionBounds(2, 2, 1)), lambda _state: False
        )
        with self.assertRaisesRegex(ValueError, "SAT"):
            WitnessProjector().project(result, PairedFixture(), witness_id="wit", query_id="query")

    def test_missing_action_field_is_rejected(self) -> None:
        fixture = PairedFixture(bounds=TransitionBounds(4, 4, 2))
        witness = WitnessProjector().project(self.sat_result(), fixture, witness_id="wit-1", query_id="query-1")
        row = dict(witness.as_dict())
        row["actions"] = [dict(witness.actions[0], message={})]
        result = NativeReplay().check(row, fixture)
        self.assertEqual(result.status, ReplayStatus.FAIL)
        self.assertIn("missing required fields", result.reason or "")

    def test_action_decoder_rejects_bad_encoding_and_unknown_fields(self) -> None:
        fixture = PairedFixture(bounds=TransitionBounds(4, 4, 2))
        witness = WitnessProjector().project(self.sat_result(), fixture, witness_id="wit-1", query_id="query-1")
        bad_nonce = dict(witness.actions[0], message=dict(witness.actions[0]["message"], nonce=-1))
        bad_extra = dict(witness.actions[0], unexpected=True)
        for row in (bad_nonce, bad_extra):
            result = NativeReplay().check(
                dict(witness.as_dict(), actions=[row]), fixture
            )
            self.assertEqual(result.status, ReplayStatus.FAIL)
            self.assertIn("invalid_witness", result.reason or "")

    def test_witness_schema_validates_projected_witness_and_rejects_extras(self) -> None:
        schema = json.loads((Path(__file__).parents[2] / "schemas" / "witness.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        fixture = PairedFixture(bounds=TransitionBounds(4, 4, 2))
        witness = WitnessProjector().project(self.sat_result(), fixture, witness_id="wit-1", query_id="query-1")
        self.assertEqual(list(validator.iter_errors(witness.as_dict())), [])
        invalid = dict(witness.as_dict(), unexpected=True)
        self.assertTrue(list(validator.iter_errors(invalid)))


if __name__ == "__main__":
    unittest.main()
