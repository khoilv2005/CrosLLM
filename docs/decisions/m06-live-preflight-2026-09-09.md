# M06.02 Ollama Cloud live preflight

Date: 2026-09-09  
Status: `RUNTIME_PREFLIGHT_PENDING`; transport/model-tag probe completed, runtime
attestation not complete.

## Command and scope

The probe used the canonical Cloud endpoint and the existing local `.env`:

```powershell
.venv\Scripts\python -m crossllm.cli preflight-live `
  --models protocol/models.json `
  --prompt-file protocol/preflight_prompt.txt `
  --responses-out build/ollama-cloud-preflight.responses.json `
  --model-lock-out build/models.lock.json `
  --endpoint https://ollama.com/api/chat `
  --env-file .env `
  --timeout-seconds 120 `
  --max-retries 0
```

This made one short connectivity/response-shape request for each declared
family. It did not run a campaign, download local weights, or send a proposal
prompt. The raw archive and model lock remain in ignored `build/` controlled
workspace storage; the API key is not copied into either file.

## Observed result

All four families returned transport success and the expected response model:

| Family | Requested tag | Response model | Transport | Served digest | Effective settings |
|---|---|---|---|---|---|
| GLM | `glm-5.3:cloud` | `glm-5.3:cloud` | pass | missing | missing |
| DeepSeek | `deepseek-v4-pro:0813-cloud` | `deepseek-v4-pro:0813-cloud` | pass | missing | missing |
| Qwen | `qwen3.5:397b-cloud` | `qwen3.5:397b-cloud` | pass | missing | missing |
| gpt-oss | `gpt-oss:120b-cloud` | `gpt-oss:120b-cloud` | pass | missing | missing |

The generated lock is `RUNTIME_PREFLIGHT_PENDING`, `preflight_ready: false`,
with lock hash
`3bc92fd34f978b78473376d702d1121abb3f5d78510461a6a1e8260ac392fdd1`.
The response archive file hash is
`fe7953b57ac15ff7464388de05e0cda17285b9a8c56824d401775580a9924ead` and the
lock file hash is
`a7e4afd4e442f9da2264bbb2f28c844e678c04335c496b61a5e4b3f6518a5633`.

## Decision

The Cloud endpoint, credential path, four family coverage and response-model
identity are operational. Ollama Cloud did not authenticate an immutable served
weight digest or return effective API settings in this chat response. The
implementation therefore preserves those fields as `null` with explicit
reasons and does not create a runtime-attestation lock or unlock evaluation.
This is the expected fail-closed outcome, not a provider transport failure.
