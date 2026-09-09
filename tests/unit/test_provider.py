from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crossllm.contracts.canonical import sha256_bytes
from crossllm.providers import (
    ArchiveReplay,
    FakeProviderServer,
    OllamaClient,
    ProviderRequest,
    ProviderResponse,
    RetryPolicy,
    TransportResponse,
    preflight_model,
)


class ProviderTests(unittest.TestCase):
    def request(self) -> ProviderRequest:
        return ProviderRequest("model:tag", "Return one invariant", {"temperature": 0.7})

    def client(self, responses, sleeps=None) -> tuple[OllamaClient, FakeProviderServer]:
        server = FakeProviderServer(responses)
        client = OllamaClient(
            sender=server.send,
            retry_policy=RetryPolicy(max_retries=2, backoff_seconds=(2.0, 10.0)),
            sleeper=(sleeps.append if sleeps is not None else (lambda _seconds: None)),
        )
        return client, server

    def test_success_captures_hashes_usage_and_request_bytes(self) -> None:
        response_body = json.dumps({
            "model": "served-model", "message": {"content": "{}"}, "done": True,
            "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 4,
        }).encode()
        client, server = self.client([
            TransportResponse(200, {"X-Model": "served-model"}, response_body)
        ])
        request = self.request()
        result = client.propose(request)
        self.assertTrue(result.ok)
        self.assertEqual(result.response_text, "{}")
        self.assertEqual(result.usage, {"prompt_tokens": 10, "generated_tokens": 4})
        self.assertEqual(len(server.requests), 1)
        self.assertEqual(result.request_hash, request.request_hash)
        self.assertEqual(result.request_body, request.body())
        self.assertEqual(result.response_body, response_body)
        self.assertEqual(result.response_headers, {"X-Model": "served-model"})
        self.assertEqual(result.response_hash, sha256_bytes(response_body))
        self.assertIsNotNone(result.elapsed_seconds)

    def test_cloud_default_uses_ollama_api_key_without_capturing_secret(self) -> None:
        class Response:
            status = 200
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"response":"ok"}'

        with patch.dict("os.environ", {"OLLAMA_API_KEY": "secret-value"}, clear=False):
            client = OllamaClient(retry_policy=RetryPolicy(max_retries=0))
            with patch("crossllm.providers.ollama.urlopen", return_value=Response()) as opened:
                result = client.propose(self.request())
        self.assertTrue(result.ok)
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://ollama.com/api/chat")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-value")
        self.assertNotIn(b"secret-value", result.request_body or b"")

    def test_cloud_client_fails_before_network_without_api_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "OLLAMA_API_KEY"):
                OllamaClient()

    def test_live_client_rejects_non_cloud_endpoint_before_network(self) -> None:
        with patch.dict("os.environ", {"OLLAMA_API_KEY": "test-key"}, clear=True):
            with self.assertRaisesRegex(ValueError, "canonical endpoint"):
                OllamaClient(endpoint="http://localhost:11434/api/chat")
            with self.assertRaisesRegex(ValueError, "canonical endpoint"):
                OllamaClient(endpoint="https://ollama.com/api/generate")

    def test_http_failure_preserves_last_raw_response_and_metadata(self) -> None:
        client, _ = self.client([
            TransportResponse(503, {"Retry-After": "10"}, b"busy"),
            TransportResponse(503, {"Retry-After": "10"}, b"busy"),
            TransportResponse(503, {"Retry-After": "10"}, b"busy"),
        ])
        result = client.propose(self.request())
        self.assertEqual(result.error, "http_failure")
        self.assertEqual(result.http_status, 503)
        self.assertEqual(result.response_body, b"busy")
        self.assertEqual(result.response_headers, {"Retry-After": "10"})
        self.assertEqual(result.response_hash, sha256_bytes(b"busy"))

    def test_retry_policy_covers_429_5xx_and_timeout(self) -> None:
        sleeps: list[float] = []
        client, server = self.client([
            TransportResponse(429, {}, b"busy"),
            TransportResponse(503, {}, b"busy"),
            TimeoutError("deadline"),
        ], sleeps)
        result = client.propose(self.request())
        self.assertEqual(result.error, "transport_failure")
        self.assertEqual(result.attempts, 3)
        self.assertEqual(sleeps, [2.0, 10.0])
        self.assertEqual(len(server.requests), 3)

    def test_cancellation_stops_before_first_provider_call(self) -> None:
        client, server = self.client([TransportResponse(200, {}, b'{"response":"unused"}')])
        result = client.propose(self.request(), cancelled=lambda: True)
        self.assertEqual(result.error, "cancelled")
        self.assertEqual(result.attempts, 0)
        self.assertEqual(server.requests, [])

    def test_cancellation_stops_retry_backoff(self) -> None:
        client, server = self.client([TimeoutError("temporary")])
        calls = iter((False, True))
        result = client.propose(self.request(), cancelled=lambda: next(calls, True))
        self.assertEqual(result.error, "cancelled")
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(server.requests), 1)

    def test_malformed_and_partial_responses_are_explicit(self) -> None:
        client, _ = self.client([TransportResponse(200, {}, b"not-json")])
        malformed = client.propose(self.request())
        self.assertEqual(malformed.error, "malformed_json")
        client, _ = self.client([TransportResponse(200, {}, json.dumps({"response": "partial", "done": False}).encode())])
        partial = client.propose(self.request())
        self.assertTrue(partial.ok)
        self.assertTrue(partial.partial)

    def test_archive_replay_is_hash_addressed(self) -> None:
        client, _ = self.client([TransportResponse(200, {}, b'{"response":"ok"}')])
        request = self.request()
        response = client.propose(request)
        archive = ArchiveReplay()
        archive.record(request, response)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "responses.json"
            archive.save(path)
            restored = ArchiveReplay.load(path)
            replayed = restored.replay(request)
            self.assertFalse(path.with_name(path.name + ".tmp").exists())
        self.assertTrue(replayed.ok)
        self.assertEqual(replayed.attempts, 1)
        self.assertEqual(replayed.request_body, request.body())
        self.assertEqual(replayed.response_body, b'{"response":"ok"}')
        self.assertEqual(restored.replay(ProviderRequest("other", "prompt", {})).error, "archive_miss")

    def test_preflight_does_not_claim_readiness_without_identity_or_effective_settings(self) -> None:
        client, _ = self.client([TransportResponse(200, {}, b'{"response":"ok"}')])
        response = client.propose(self.request())
        result = preflight_model({"family": "Qwen", "requested_tag": "model:tag"}, response)
        self.assertFalse(result.ready)
        self.assertIsNone(result.served_weight_digest)
        self.assertIn("served_weight_digest", result.missing_field_reasons)

    def test_provider_archive_rejects_invalid_identity_usage_and_elapsed_values(self) -> None:
        client, _ = self.client([TransportResponse(200, {}, b'{"response":"ok"}')])
        response = client.propose(self.request()).as_dict()
        for field, value in (
            ("request_hash", ""),
            ("usage", {"prompt_tokens": -1}),
            ("elapsed_seconds", -1.0),
        ):
            payload = dict(response)
            payload[field] = value
            with self.assertRaisesRegex(ValueError, "provider archive"):
                ProviderResponse.from_dict(payload)

    def test_provider_archive_rejects_raw_capture_hash_tampering(self) -> None:
        client, _ = self.client([TransportResponse(200, {}, b'{"response":"ok"}')])
        payload = client.propose(self.request()).as_dict()
        tampered_request = dict(payload)
        tampered_request["request_body_b64"] = "dGFtcGVyZWQ="  # b"tampered"
        with self.assertRaisesRegex(ValueError, "request body hash mismatch"):
            ProviderResponse.from_dict(tampered_request)
        tampered_response = dict(payload)
        tampered_response["response_body_b64"] = "dGFtcGVyZWQ="
        with self.assertRaisesRegex(ValueError, "response body hash mismatch"):
            ProviderResponse.from_dict(tampered_response)


if __name__ == "__main__":
    unittest.main()
