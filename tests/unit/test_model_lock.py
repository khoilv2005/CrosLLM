from __future__ import annotations

import unittest

from crossllm.contracts.canonical import sha256_hex
from crossllm.providers import (
    PreflightPanel,
    PreflightResult,
    ProviderResponse,
    build_runtime_model_lock,
)


FAMILIES = ("GLM", "DeepSeek", "Qwen", "gpt-oss")


def response(family: str, *, error: str | None = None) -> ProviderResponse:
    return ProviderResponse(
        request_hash=f"request-{family}", response_hash=f"response-{family}", http_status=200,
        response_text="secret candidate text", response_model=f"served-{family}",
        finish_reason="stop", usage={"prompt_tokens": 2, "generated_tokens": 3},
        attempts=1, partial=False, error=error,
    )


def result(family: str, *, ready: bool = True) -> PreflightResult:
    return PreflightResult(
        family=family,
        requested_tag=f"{family.lower()}:cloud",
        ready=ready,
        response_model=f"served-{family}",
        served_weight_digest=f"sha256:{family.lower()}" if ready else None,
        effective_settings={"temperature": 0.5} if ready else None,
        missing_field_reasons={} if ready else {"transport": "provider failure"},
        checks=(),
    )


class RuntimeModelLockTests(unittest.TestCase):
    def metadata(self, family: str) -> dict[str, object]:
        return {
            "family": family,
            "model": f"{family}-model",
            "requested_tag": f"{family.lower()}:cloud",
            "upstream_weights": f"upstream/{family}",
            "license": "Apache-2.0",
            "license_source": f"https://example.test/{family}/LICENSE",
            "public_weight_and_license_evidence": "public evidence",
            "sources": [f"https://example.test/{family}"],
        }

    def document(self) -> dict[str, object]:
        return {
            "provider": {
                "name": "ollama_cloud",
                "base_url": "https://ollama.com",
                "chat_endpoint": "https://ollama.com/api/chat",
                "auth_env": "OLLAMA_API_KEY",
                "execution_mode": "remote_cloud_api",
                "local_weights": False,
                "api_key": "must-not-appear",
            },
            "secret": "must-not-appear",
        }

    def test_lock_is_hash_addressed_and_excludes_secrets_and_response_text(self) -> None:
        panel = PreflightPanel(tuple(result(family) for family in FAMILIES), FAMILIES)
        lock = build_runtime_model_lock(
            self.document(), [self.metadata(family) for family in FAMILIES], panel,
            {family: response(family) for family in FAMILIES},
            captured_at="2026-09-08T00:00:00+00:00",
        )
        without_hash = dict(lock)
        lock_hash = without_hash.pop("lock_hash")
        self.assertEqual(lock_hash, sha256_hex(without_hash))
        serialized = str(lock)
        self.assertNotIn("must-not-appear", serialized)
        self.assertNotIn("secret candidate text", serialized)
        self.assertEqual(lock["status"], "RUNTIME_ATTESTATION_LOCKED")
        self.assertEqual(lock["models"][0]["immutable_served_weights_guaranteed"], False)
        self.assertIn("identity_limitations", lock["models"][0])

    def test_blocked_panel_is_explicitly_pending(self) -> None:
        panel = PreflightPanel(tuple(result(family, ready=family != "Qwen") for family in FAMILIES), FAMILIES)
        lock = build_runtime_model_lock(
            self.document(), [self.metadata(family) for family in FAMILIES], panel,
            {family: response(family, error="provider_failure") if family == "Qwen" else response(family) for family in FAMILIES},
            captured_at="2026-09-08T00:00:00+00:00",
        )
        self.assertFalse(lock["preflight_ready"])
        self.assertEqual(lock["status"], "RUNTIME_PREFLIGHT_PENDING")
        self.assertEqual(lock["models"][2]["preflight_status"], "blocked")


if __name__ == "__main__":
    unittest.main()
