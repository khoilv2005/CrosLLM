from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crossllm.cli import main
from crossllm.providers import ProviderResponse, preflight_panel


class CLIPreflightTests(unittest.TestCase):
    families = ("GLM", "DeepSeek", "Qwen", "gpt-oss")

    def metadata(self, family: str) -> dict[str, object]:
        return {
            "family": family,
            "preferred_execution_tag": f"{family.lower()}:cloud",
            "served_weight_digest": "sha256:" + family.lower(),
            "effective_api_settings": {"temperature": 0.7},
        }

    def response(self, family: str) -> ProviderResponse:
        return ProviderResponse(
            request_hash=f"request-{family}", response_hash=f"response-{family}",
            http_status=200, response_text="{}", response_model=f"served-{family}",
            finish_reason="stop", usage={"prompt_tokens": 1, "generated_tokens": 1},
            attempts=1, partial=False,
        )

    def run_cli(self, models: Path, responses: Path) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["preflight", "--models", str(models), "--responses", str(responses)])
        return code, json.loads(output.getvalue())

    def test_preflight_reads_all_four_archived_responses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = root / "models.json"
            responses = root / "responses.json"
            models.write_text(json.dumps({"models": [self.metadata(f) for f in self.families]}), encoding="utf-8")
            responses.write_text(json.dumps({f: self.response(f).as_dict() for f in self.families}), encoding="utf-8")
            code, output = self.run_cli(models, responses)
            self.assertEqual(code, 0)
            self.assertTrue(output["ready"])

    def test_preflight_returns_nonzero_for_missing_family_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = root / "models.json"
            responses = root / "responses.json"
            models.write_text(json.dumps({"models": [self.metadata(f) for f in self.families]}), encoding="utf-8")
            responses.write_text(json.dumps({f: self.response(f).as_dict() for f in self.families[:-1]}), encoding="utf-8")
            code, output = self.run_cli(models, responses)
            self.assertEqual(code, 3)
            self.assertFalse(output["ready"])

    def test_live_preflight_can_write_public_runtime_model_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = root / "models.json"
            prompt = root / "prompt.txt"
            responses_out = root / "responses.json"
            lock_out = root / "models.lock.json"
            rows = [self.metadata(family) for family in self.families]
            models.write_text(json.dumps({
                "provider": {
                    "name": "ollama_cloud", "base_url": "https://ollama.com",
                    "chat_endpoint": "https://ollama.com/api/chat", "auth_env": "OLLAMA_API_KEY",
                    "execution_mode": "remote_cloud_api", "local_weights": False,
                },
                "models": rows,
            }), encoding="utf-8")
            prompt.write_text("preflight", encoding="utf-8")
            responses = {family: self.response(family) for family in self.families}
            panel = preflight_panel(rows, responses)
            output = io.StringIO()
            with patch.dict(os.environ, {"OLLAMA_API_KEY": "test-key"}, clear=False):
                with patch("crossllm.cli.run_live_preflight", return_value=(panel, responses)):
                    with contextlib.redirect_stdout(output):
                        code = main([
                            "preflight-live", "--models", str(models), "--prompt-file", str(prompt),
                            "--responses-out", str(responses_out), "--model-lock-out", str(lock_out),
                        ])
            self.assertEqual(code, 0)
            printed = json.loads(output.getvalue())
            lock = json.loads(lock_out.read_text(encoding="utf-8"))
            self.assertEqual(printed["model_lock_hash"], lock["lock_hash"])
            self.assertNotIn("test-key", json.dumps(lock))
            self.assertNotIn("response_text", json.dumps(lock))

    def test_live_preflight_loads_explicit_env_file_without_printing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = root / "models.json"
            prompt = root / "prompt.txt"
            env_file = root / ".env"
            responses_out = root / "responses.json"
            rows = [self.metadata(family) for family in self.families]
            models.write_text(json.dumps({
                "provider": {
                    "name": "ollama_cloud", "base_url": "https://ollama.com",
                    "chat_endpoint": "https://ollama.com/api/chat", "auth_env": "OLLAMA_API_KEY",
                    "execution_mode": "remote_cloud_api", "local_weights": False,
                },
                "models": rows,
            }), encoding="utf-8")
            prompt.write_text("preflight", encoding="utf-8")
            env_file.write_text("# fixture only\nOLLAMA_API_KEY=fixture-secret\n", encoding="utf-8")
            responses = {family: self.response(family) for family in self.families}
            panel = preflight_panel(rows, responses)
            output = io.StringIO()
            with patch.dict(os.environ, {}, clear=True):
                with patch("crossllm.cli.run_live_preflight", return_value=(panel, responses)):
                    with contextlib.redirect_stdout(output):
                        code = main([
                            "preflight-live", "--models", str(models), "--prompt-file", str(prompt),
                            "--responses-out", str(responses_out), "--env-file", str(env_file),
                        ])
            self.assertEqual(code, 0)
            self.assertNotIn("fixture-secret", output.getvalue())
            self.assertTrue(responses_out.exists())

    def test_live_preflight_rejects_non_cloud_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = root / "models.json"
            prompt = root / "prompt.txt"
            models.write_text(json.dumps({"models": [self.metadata(family) for family in self.families]}), encoding="utf-8")
            prompt.write_text("preflight", encoding="utf-8")
            with patch.dict(os.environ, {"OLLAMA_API_KEY": "fixture-secret"}, clear=False):
                with self.assertRaises(SystemExit) as error:
                    main([
                        "preflight-live", "--models", str(models), "--prompt-file", str(prompt),
                        "--responses-out", str(root / "responses.json"),
                        "--endpoint", "http://localhost:11434/api/chat",
                    ])
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
