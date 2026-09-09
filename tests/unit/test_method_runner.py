from __future__ import annotations

import json
import unittest

from crossllm.xlir import XLIRCompiler
from crossllm.contracts.canonical import sha256_hex
from crossllm.methods import MethodRunner, MethodTrack, PromptPolicy, PromptTemplate, candidate_identity
from crossllm.providers import FakeProviderServer, OllamaClient, TokenBudget, TransportResponse
from crossllm.runtime import AppendOnlyEventStore, append_method_run_events


class MethodRunnerTests(unittest.TestCase):
    def test_serialized_canonical_hash_must_match_body_before_semantic_dedup(self) -> None:
        payload = {
            "kind": "invariant",
            "invariant_id": None,
            "body": {"kind": "literal", "type": "bool", "value": True},
            "canonical_hash": "0" * 64,
            "node_count": 1,
        }
        raw_hash, semantic_hash = candidate_identity(payload)
        self.assertEqual(raw_hash, candidate_identity(payload)[0])
        self.assertIsNone(semantic_hash)

        payload["canonical_hash"] = sha256_hex(payload["body"])
        verified_hash, verified_semantic_hash = candidate_identity(payload)
        self.assertEqual(verified_hash, payload["canonical_hash"])
        self.assertEqual(verified_semantic_hash, payload["canonical_hash"])

    def test_compiled_invariant_duplicates_use_canonical_ast_hash_and_keep_slot_denominator(self) -> None:
        candidate_payload = {
            "kind": "invariant",
            "body": {"kind": "literal", "type": "bool", "value": True},
        }
        compiled = XLIRCompiler.from_symbols([]).compile(candidate_payload)
        self.assertTrue(compiled.ok, compiled.diagnostics)
        assert compiled.invariant is not None
        payload = json.dumps({"model": "served", "response": json.dumps(candidate_payload), "done": True}).encode()
        server = FakeProviderServer([TransportResponse(200, {}, payload) for _ in range(8)])
        run = MethodRunner(OllamaClient(sender=server.send)).run(
            track=MethodTrack.CROSSLLM,
            backbone="GLM",
            model="glm:test",
            attempt_id="attempt-canonical-duplicate",
            template=PromptTemplate("x", "v1", "{artifact_pack}"),
            artifact_pack_text="pack",
            artifact_pack_hash="f" * 64,
            settings={},
            parse_candidate=lambda _text: compiled.invariant,
        )
        self.assertEqual(run.slots[0].status.value, "candidate")
        self.assertTrue(all(slot.status.value == "duplicate" for slot in run.slots[1:]))
        self.assertEqual(run.slots[0].canonical_ast_hash, compiled.invariant.canonical_hash)
        self.assertTrue(all(slot.canonical_ast_hash == compiled.invariant.canonical_hash for slot in run.slots[1:]))
        self.assertEqual(len(run.slots), 8)
    def test_x_p_t0_runner_uses_same_prompt_settings_and_eight_requests(self) -> None:
        candidates = [json.dumps({
            "kind": "invariant", "body": {"kind": "literal", "type": "bool", "value": True}, "slot": index,
        }) for index in range(8)]
        server = FakeProviderServer([
            TransportResponse(200, {}, json.dumps({"model": "served", "response": candidate, "done": True}).encode())
            for candidate in candidates
        ])
        client = OllamaClient(sender=server.send)
        template = PromptTemplate("t0", "v1", "Audit:\n{artifact_pack}")
        run = MethodRunner(client).run(
            track=MethodTrack.T0,
            backbone="Qwen",
            model="qwen:test",
            attempt_id="attempt-1",
            template=template,
            artifact_pack_text="public pack",
            artifact_pack_hash="a" * 64,
            settings={"temperature": 0.6, "top_p": 0.95},
            parse_candidate=lambda text: json.loads(text),
        )
        self.assertEqual(run.track, MethodTrack.T0)
        self.assertEqual(len(run.slots), 8)
        self.assertTrue(all(slot.status.value == "candidate" for slot in run.slots))
        self.assertEqual(len(server.requests), 8)
        self.assertEqual(len({request for request in server.requests}), 1)

    def test_duplicate_candidates_consume_slots_without_becoming_findings(self) -> None:
        candidate = json.dumps({"kind": "invariant", "body": {"kind": "literal", "type": "bool", "value": True}})
        payload = json.dumps({"model": "served", "response": candidate, "done": True}).encode()
        server = FakeProviderServer([TransportResponse(200, {}, payload) for _ in range(8)])
        run = MethodRunner(OllamaClient(sender=server.send)).run(
            track=MethodTrack.CROSSLLM,
            backbone="GLM",
            model="glm:test",
            attempt_id="attempt-duplicate",
            template=PromptTemplate("x", "v1", "{artifact_pack}"),
            artifact_pack_text="pack",
            artifact_pack_hash="b" * 64,
            settings={},
            parse_candidate=lambda text: json.loads(text),
        )
        self.assertEqual(run.slots[0].status.value, "candidate")
        self.assertTrue(all(slot.status.value == "duplicate" for slot in run.slots[1:]))

    def test_invalid_response_still_consumes_slot(self) -> None:
        payload = json.dumps({"model": "served", "response": "not-json", "done": True}).encode()
        server = FakeProviderServer([TransportResponse(200, {}, payload) for _ in range(8)])
        run = MethodRunner(OllamaClient(sender=server.send)).run(
            track=MethodTrack.CROSSLLM,
            backbone="GLM",
            model="glm:test",
            attempt_id="attempt-2",
            template=PromptTemplate("x", "v1", "{artifact_pack}"),
            artifact_pack_text="pack",
            artifact_pack_hash="b" * 64,
            settings={},
        )
        self.assertTrue(all(slot.status.value == "invalid" for slot in run.slots))

    def test_response_model_drift_is_provider_failure_and_not_candidate(self) -> None:
        candidate = json.dumps({
            "kind": "invariant",
            "body": {"kind": "literal", "type": "bool", "value": True},
        })
        payload = json.dumps({"model": "unexpected-model", "response": candidate, "done": True}).encode()
        server = FakeProviderServer([TransportResponse(200, {}, payload) for _ in range(8)])
        run = MethodRunner(OllamaClient(sender=server.send)).run(
            track=MethodTrack.CROSSLLM,
            backbone="GLM",
            model="glm:test",
            expected_response_model="glm:test",
            attempt_id="attempt-model-drift",
            template=PromptTemplate("x", "v1", "{artifact_pack}"),
            artifact_pack_text="pack",
            artifact_pack_hash="b" * 64,
            settings={},
            parse_candidate=lambda text: json.loads(text),
        )
        self.assertTrue(all(slot.status.value == "provider_failure" for slot in run.slots))
        self.assertTrue(all(slot.reason == "response_model_mismatch" for slot in run.slots))
        self.assertEqual(len(run.provider_responses), 8)

    def test_provider_usage_is_capped_without_a_local_tokenizer(self) -> None:
        payloads = []
        for slot in range(8):
            candidate = json.dumps({
                "kind": "invariant",
                "body": {"kind": "literal", "type": "bool", "value": True},
                "slot": slot,
            })
            payloads.append(TransportResponse(200, {}, json.dumps({
                "model": "served", "response": candidate, "done": True,
                "prompt_eval_count": 99, "eval_count": 1,
            }).encode()))
        server = FakeProviderServer(payloads)
        run = MethodRunner(
            OllamaClient(sender=server.send),
            token_budget=TokenBudget(input_native_token_cap=10, generated_native_token_cap=10),
        ).run(
            track=MethodTrack.DIRECT,
            backbone="GLM",
            model="glm:test",
            attempt_id="attempt-usage-cap",
            template=PromptTemplate("p", "v1", "{artifact_pack}"),
            artifact_pack_text="pack",
            artifact_pack_hash="c" * 64,
            settings={},
            parse_candidate=lambda text: json.loads(text),
        )
        self.assertTrue(all(slot.status.value == "invalid" for slot in run.slots))
        self.assertEqual(len(run.budget_checks), 8)
        self.assertTrue(all(check.reason == "input_token_cap_exceeded" for check in run.budget_checks))

    def test_budget_rejection_does_not_mark_later_same_payload_as_duplicate(self) -> None:
        candidate = json.dumps({
            "kind": "invariant",
            "body": {"kind": "literal", "type": "bool", "value": True},
        })
        payload = json.dumps({
            "model": "served", "response": candidate, "done": True,
            "prompt_eval_count": 99, "eval_count": 1,
        }).encode()
        server = FakeProviderServer([TransportResponse(200, {}, payload) for _ in range(8)])
        run = MethodRunner(
            OllamaClient(sender=server.send),
            token_budget=TokenBudget(input_native_token_cap=10, generated_native_token_cap=10),
        ).run(
            track=MethodTrack.DIRECT,
            backbone="GLM",
            model="glm:test",
            attempt_id="attempt-budget-duplicate",
            template=PromptTemplate("p", "v1", "{artifact_pack}"),
            artifact_pack_text="pack",
            artifact_pack_hash="d" * 64,
            settings={},
            parse_candidate=lambda text: json.loads(text),
        )
        self.assertTrue(all(slot.status.value == "invalid" for slot in run.slots))

    def test_missing_provider_usage_is_recorded_as_unknown_without_rejecting_candidate(self) -> None:
        payloads = []
        for slot in range(8):
            candidate = json.dumps({
                "kind": "invariant",
                "body": {"kind": "literal", "type": "bool", "value": True},
                "slot": slot,
            })
            payloads.append(TransportResponse(200, {}, json.dumps({
                "model": "served", "response": candidate, "done": True,
            }).encode()))
        server = FakeProviderServer(payloads)
        run = MethodRunner(OllamaClient(sender=server.send)).run(
            track=MethodTrack.DIRECT,
            backbone="GLM",
            model="glm:test",
            attempt_id="attempt-usage-unknown",
            template=PromptTemplate("p", "v1", "{artifact_pack}"),
            artifact_pack_text="pack",
            artifact_pack_hash="c" * 64,
            settings={},
            parse_candidate=lambda text: json.loads(text),
        )
        self.assertTrue(all(slot.status.value == "candidate" for slot in run.slots))
        self.assertEqual(len(run.budget_checks), 8)
        self.assertTrue(all(check.status.value == "unknown" for check in run.budget_checks))

    def test_cancellation_preserves_all_slots_as_provider_failures(self) -> None:
        server = FakeProviderServer([])
        run = MethodRunner(OllamaClient(sender=server.send)).run(
            track=MethodTrack.CROSSLLM,
            backbone="Qwen",
            model="qwen:test",
            attempt_id="attempt-cancelled",
            template=PromptTemplate("x", "v1", "{artifact_pack}"),
            artifact_pack_text="pack",
            artifact_pack_hash="b" * 64,
            settings={},
            cancelled=lambda: True,
            campaign_deadline_seconds=30.0,
        )
        self.assertEqual(len(run.slots), 8)
        self.assertTrue(all(slot.status.value == "provider_failure" for slot in run.slots))
        self.assertEqual(server.requests, [])

    def test_slot_count_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "slot counts"):
            MethodRunner(OllamaClient(sender=FakeProviderServer([]).send)).run(
                track=MethodTrack.DIRECT,
                backbone="DeepSeek",
                model="deepseek:test",
                attempt_id="attempt-3",
                template=PromptTemplate("p", "v1", "{artifact_pack}", policy=PromptPolicy(proposal_slots=4)),
                artifact_pack_text="pack",
                artifact_pack_hash="c" * 64,
                settings={},
            )

    def test_runtime_event_projection_rejects_provider_credentials(self) -> None:
        candidate = json.dumps({
            "kind": "invariant",
            "body": {"kind": "literal", "type": "bool", "value": True},
        })
        payload = json.dumps({"model": "served", "response": candidate, "done": True}).encode()
        server = FakeProviderServer([TransportResponse(200, {}, payload) for _ in range(8)])
        run = MethodRunner(OllamaClient(sender=server.send)).run(
            track=MethodTrack.CROSSLLM,
            backbone="GLM",
            model="glm:test",
            attempt_id="attempt-secret",
            template=PromptTemplate("x", "v1", "{artifact_pack}"),
            artifact_pack_text="pack",
            artifact_pack_hash="b" * 64,
            settings={"api_key": "must-not-be-archived"},
            parse_candidate=lambda text: json.loads(text),
        )
        store = AppendOnlyEventStore()
        with self.assertRaisesRegex(ValueError, "credentials"):
            append_method_run_events(
                store,
                run,
                campaign_id="campaign-secret",
                timestamp="2026-09-08T00:00:00Z",
            )
        self.assertEqual(store.events, ())


if __name__ == "__main__":
    unittest.main()
