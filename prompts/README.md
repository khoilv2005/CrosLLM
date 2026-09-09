# Versioned prompts

The three text files in this directory are public, hashable prompt assets for
the CrossLLM, direct-audit and fixed-template tracks. Each has exactly one
`{artifact_pack}` placeholder and forbids memory, tools and retrieval. The
artifact pack is the only target-specific input.

`protocol/preflight_prompt.txt` is separate: it is a neutral Ollama Cloud
connectivity/response-shape probe and is not a proposal prompt.

Before an evaluation request, hash these files and bind their hashes into the
runtime lock. Changing prompt text, version or policy creates a new lock; do
not silently mix prompt revisions in one campaign.
