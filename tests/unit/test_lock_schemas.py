from __future__ import annotations

import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from crossllm.contracts.canonical import sha256_hex
from crossllm.providers import PreflightPanel, PreflightResult, ProviderResponse, build_runtime_model_lock
from crossllm.runtime import build_protocol_lock


class LockSchemaTests(unittest.TestCase):
    root = Path(__file__).parents[2]

    def test_model_lock_schema_accepts_public_runtime_lock(self) -> None:
        families = ("GLM", "DeepSeek", "Qwen", "gpt-oss")
        metadata = [
            {
                "family": family,
                "model": f"{family}-model",
                "upstream_weights": f"upstream/{family}",
                "license": "Apache-2.0",
                "license_source": "https://example.test/license",
                "sources": ["https://example.test/model"],
            }
            for family in families
        ]
        responses = {
            family: ProviderResponse(
                request_hash="a" * 64,
                response_hash="b" * 64,
                http_status=200,
                response_text="discarded",
                response_model=f"served-{family}",
                finish_reason="stop",
                usage={"prompt_tokens": 1, "generated_tokens": 1},
                attempts=1,
                partial=False,
            )
            for family in families
        }
        panel = PreflightPanel(tuple(
            PreflightResult(
                family, f"{family.lower()}:cloud", True, f"served-{family}", None,
                {"temperature": 0.7}, {}, (),
            )
            for family in families
        ), families)
        lock = build_runtime_model_lock(
            {"provider": {
                "name": "ollama_cloud", "base_url": "https://ollama.com",
                "chat_endpoint": "https://ollama.com/api/chat", "auth_env": "OLLAMA_API_KEY",
                "execution_mode": "remote_cloud_api", "local_weights": False,
            }}, metadata, panel, responses, captured_at="2026-09-08T00:00:00+00:00",
        )
        validator = Draft202012Validator(json.loads((self.root / "schemas/model_lock.schema.json").read_text(encoding="utf-8")))
        self.assertEqual(list(validator.iter_errors(lock)), [])
        invalid = dict(lock, api_key="must-not-appear")
        self.assertTrue(list(validator.iter_errors(invalid)))

    def test_protocol_lock_schema_accepts_only_complete_lock(self) -> None:
        protocol = {
            "schema_version": 2,
            "model_families": ["GLM"],
            "budgets": {"campaign_wall_seconds": 3600},
            "proposal_slots": 8,
            "evaluation_replicates": 10,
            "missing_execution_fields": [],
        }
        lock = build_protocol_lock(
            protocol,
            model_lock_hash="a" * 64,
            benchmark_manifest_hash="b" * 64,
            captured_at="2026-09-08T00:00:00Z",
            dependency_hashes={"toolchain": "c" * 64},
        )
        validator = Draft202012Validator(json.loads((self.root / "schemas/protocol_lock.schema.json").read_text(encoding="utf-8")))
        self.assertEqual(list(validator.iter_errors(lock)), [])
        invalid = dict(lock, missing_execution_fields=["late change"])
        self.assertTrue(list(validator.iter_errors(invalid)))


if __name__ == "__main__":
    unittest.main()
