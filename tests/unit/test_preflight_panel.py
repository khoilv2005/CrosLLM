from __future__ import annotations

import json
import unittest

from crossllm.providers import (
    FakeProviderServer,
    OllamaClient,
    ProviderResponse,
    RetryPolicy,
    TransportResponse,
    preflight_panel,
    run_live_preflight,
)


def response(family: str) -> ProviderResponse:
    return ProviderResponse(
        request_hash=f"request-{family}", response_hash=f"response-{family}", http_status=200,
        response_text="{}", response_model=f"served-{family}", finish_reason="stop",
        usage={"prompt_tokens": 1, "generated_tokens": 1}, attempts=1, partial=False,
    )


class PreflightPanelTests(unittest.TestCase):
    def metadata(self, family: str) -> dict[str, object]:
        return {
            "family": family, "preferred_execution_tag": f"{family.lower()}:cloud",
            "served_weight_digest": f"sha256:{family}",
            "effective_api_settings": {"temperature": 0.5},
        }

    def test_all_four_family_results_are_serialized_and_ready(self) -> None:
        families = ("GLM", "DeepSeek", "Qwen", "gpt-oss")
        panel = preflight_panel(
            [self.metadata(family) for family in families],
            {family: response(family) for family in families},
        )
        self.assertTrue(panel.ready)
        self.assertEqual(len(panel.as_dict()["results"]), 4)
        self.assertTrue(all(result.ready for result in panel.results))

    def test_missing_family_is_not_silently_dropped(self) -> None:
        families = ("GLM", "DeepSeek", "Qwen", "gpt-oss")
        panel = preflight_panel(
            [self.metadata(family) for family in families[:-1]],
            {family: response(family) for family in families[:-1]},
        )
        self.assertFalse(panel.ready)
        missing = next(result for result in panel.results if result.family == "gpt-oss")
        self.assertFalse(missing.ready)
        self.assertEqual(missing.missing_field_reasons["panel"], "metadata_or_response_missing")

    def test_duplicate_family_metadata_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate"):
            preflight_panel(
                [self.metadata("GLM"), self.metadata("GLM")],
                {"GLM": response("GLM")},
            )

    def test_unexpected_family_is_rejected_before_live_calls(self) -> None:
        families = ("GLM", "DeepSeek", "Qwen", "gpt-oss")
        metadata = [self.metadata(family) | {"starting_research_settings": {"temperature": 0.5}} for family in families]
        metadata.append(self.metadata("unregistered"))
        server = FakeProviderServer([])
        with self.assertRaisesRegex(ValueError, "unexpected model families"):
            run_live_preflight(
                metadata,
                "preflight",
                OllamaClient(sender=server.send, retry_policy=RetryPolicy(max_retries=0)),
            )
        self.assertEqual(server.requests, [])

    def test_live_preflight_uses_requested_tags_and_returns_captured_responses(self) -> None:
        families = ("GLM", "DeepSeek", "Qwen", "gpt-oss")
        metadata = [self.metadata(family) | {"starting_research_settings": {"temperature": 0.5}} for family in families]
        server = FakeProviderServer([
            TransportResponse(200, {}, json.dumps({"model": family, "message": {"content": "ok"}, "done": True}).encode())
            for family in families
        ])
        panel, responses = run_live_preflight(
            metadata,
            "preflight",
            OllamaClient(sender=server.send, retry_policy=RetryPolicy(max_retries=0)),
        )
        self.assertTrue(panel.ready)
        self.assertEqual(sorted(responses), sorted(families))
        self.assertEqual(len(server.requests), 4)
        self.assertEqual(json.loads(server.requests[0])["model"], "glm:cloud")


if __name__ == "__main__":
    unittest.main()
