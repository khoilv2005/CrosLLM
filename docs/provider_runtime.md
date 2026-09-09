# Provider transport and preflight boundary

The provider foundation implements the M06.01 transport contract in
`src/crossllm/providers/ollama.py`:

The live execution path is Ollama Cloud, not local model serving. Production
requests use `https://ollama.com/api/chat` with the `OLLAMA_API_KEY` secret.
No model weights are downloaded, mounted or executed by this repository. A
local Ollama endpoint is still permitted for fake/archive and isolated
development tests when passed explicitly as an endpoint override.

- canonical request bytes and request hash;
- one-request/one-candidate response records;
- canonical request bytes and captured response bytes (base64 in archives),
  request/response hashes, HTTP status/headers, response model, finish reason,
  usage, elapsed time and partial-response fields;
- retries only for 429, 5xx and transport timeout/failure, capped at two with
  the protocol backoff values;
- malformed JSON, missing content, archive misses and provider failures kept as
  explicit errors rather than converted to abstention or success;
- hash-addressed archive save/load/replay (including backward-compatible reads
  of pre-capture archives), raw request/response bytes are verified against
  their declared hashes when present, atomic archive writes and queue-based
  fake server for tests.

`preflight_model` implements the conservative M06.02 boundary. A model is not
ready unless a requested tag, transport response, served identity and effective
settings are all present. Missing served-weight digest or effective settings is
retained in `missing_field_reasons`; catalogue metadata alone cannot create an
execution lock.

`preflight_panel` aggregates the four required families (GLM, DeepSeek, Qwen and
gpt-oss), inserts an explicit blocked result for a missing family/response and
rejects duplicate or unexpected family metadata. `run_live_preflight` performs
the same allowlist check before its first provider call. Its `ready` bit is true
only when all four per-family checks pass.

The evaluation readiness gate also requires the model lock's provider block to
declare Ollama Cloud, the canonical `ollama.com/api/chat` endpoint,
`OLLAMA_API_KEY` authentication, remote-cloud execution and
`local_weights: false`. A model list with four rows but a local-serving or
ambiguous provider block is rejected before evaluation.

The offline CLI boundary is:

```text
crossllm preflight --models protocol/models.json --responses preflight.responses.json
```

The response file is an archive-shaped mapping from family to
`ProviderResponse`; exit code `3` means the panel is not ready. This command
does not manufacture a live call, served-weight identity, license evidence or
effective settings, so a development archive cannot unlock evaluation.

For an explicitly authorized live probe, `crossllm preflight-live` uses the
same transport and stores the captured archive:

```text
crossllm preflight-live --models protocol/models.json \
  --prompt-file configs/preflight_prompt.txt \
  --responses-out controlled/preflight.responses.json \
  --model-lock-out controlled/models.lock.json \
  --endpoint https://ollama.com/api/chat \
  --env-file .env
```

The live CLI is deliberately Cloud-only: it requires the canonical endpoint
and a model document whose provider block declares `ollama_cloud`, remote API
execution and `local_weights: false`. Local endpoints remain available only to
the injected fake/archive transport used by development tests.

The CLI loads `OLLAMA_API_KEY` from `.env` by default (or from the explicit
`--env-file` path). The key is used only as an HTTP Bearer credential and is
never written into the captured request body or response archive. `.env` is a
local credential file and must remain ignored by Git.
The cloud client fails before its first network request when this key is
missing, so a misconfigured worker does not spend retry attempts on 401 calls.

For a Docker worker, inject the same file with Docker's `--env-file` option;
do not bind-mount `.env` into the container. The default worker policy
allowlists only `ollama.com`, and provider-enabled workers use bridge egress
only for the Ollama Cloud endpoint. Offline workers remain on
`--network=none`.

Its nonzero result is intentional when the provider does not return immutable
served-weight or effective-setting evidence. The command never fills those
fields from the requested tag or local catalogue metadata.

`ExactTokenCounter` is the separate preflight-side boundary for M06.03. It
requires an explicit encoding ID, revision, artifact hash and injected encoder,
counts both prompt and generated text, and has no byte/word fallback.
Unavailable tokenizer support therefore remains explicit `null` with a reason;
it cannot silently affect cap or cost decisions.

`MethodRunner` can receive an `ExactTokenCounter` and `TokenBudget`. It records
controlled provider responses, per-slot tokenizer measurements and budget
checks. Provider-reported Ollama usage is checked even when no local tokenizer
is available; when an explicit tokenizer is supplied, its measurement is also
used for the cap decision. A cap violation consumes the slot but becomes
`invalid` rather than an analyzable candidate, while unavailable counts remain
`unknown` and are not treated as proof of compliance. The prompt template hash
binds template ID,
version, text and the no-memory/tools/retrieval policy, and templates must use
exactly one public artifact-pack placeholder.

Within one method attempt, canonical-equivalent candidates after the first are
recorded as `duplicate`; they consume their ordered slots and retain response
hashes, but are not passed downstream as new proposals.

The 2026-09-09 live preflight exercised all four model families and returned the
expected response model for each. It remains `RUNTIME_PREFLIGHT_PENDING` because
the chat response did not authenticate immutable served-weight identities or
return effective API settings; these fields stay `null` with reasons in the
controlled `build/models.lock.json`. M06.06–M06.07 still require frozen runtime
settings and model-specific tokenizers. Cloud quota, availability and
provider-reported identity remain runtime facts; they cannot be manufactured
from the requested tag or from upstream weight metadata. See
`docs/decisions/m06-live-preflight-2026-09-09.md` for the non-secret hashes.

The public prompt assets are in `prompts/` and their content hashes are listed
in `prompts/manifest.json`. `protocol/preflight_prompt.txt` is a separate
neutral connectivity probe; it must not be treated as a proposal prompt.

When `--model-lock-out` is supplied, the command also writes a public,
hash-addressed `models.lock.json`. It contains allowlisted catalogue and
license/source fields, captured request/response hashes, response model,
effective settings, usage and per-family preflight checks. It never copies the
API key, response text, raw headers or arbitrary metadata fields. A passing
panel is marked `RUNTIME_ATTESTATION_LOCKED`; a panel with incomplete evidence
is marked `RUNTIME_PREFLIGHT_PENDING` and records explicit identity limitations.
The lock hash can be passed to the campaign planner; writing it does not itself
make evaluation ready.
Therefore the provider layer remains suitable for fake/archive development
tests only, not evaluation.
