# Offline development dry-run

`src/crossllm/runtime/dry_run.py` composes the current development-only
boundaries over an in-memory fixture: XLIR proposal compilation, a grounded Z3
formula check, exhaustive bounded search and an independent symbolic bounded
search with native differential replay, native witness projection/replay, all
three X/P/T0 method tracks through a fake Ollama transport, event interruption
and same-attempt resume, JSONL export, synthetic analysis and resource
telemetry. It makes no Cloud provider request and does not exercise an
independent EVM.

The rehearsal is covered by `tests/unit/test_runtime_dry_run.py`. Its result is
an engineering smoke test only; it cannot promote the synthetic fixture,
pre-generated traces or public benchmark rows into admitted evaluation evidence.

The report also contains the replay assessment state. The synthetic run is
`pending`, because native replay passes but independent EVM replay and security
relevance are intentionally unassessed. `pending` is distinct from a hard
replay failure (`rejected`) and from fully evidenced replay (`confirmed`).

Run it from the repository root with:

```bash
crossllm dry-run --export build/development-dry-run.events.jsonl
```

The command prints a JSON report and writes append-only event records. A normal
run exports 58 records: four campaign lifecycle records plus 54 method records
(three tracks, eight provider responses and eight consumed proposal slots per
track). The export parent directory is created when needed; no evaluation data
or Cloud provider request is created by this command. To exercise explicit
failure handling as well:

```bash
crossllm dry-run \
  --export build/development-dry-run.events.jsonl \
  --fault-export build/development-faults.events.jsonl
```

The fault rehearsal injects worker crash/restart, timeout, corrupted blob,
disk-full and provider outage callbacks. It checks event/status policy and
atomic export, but it is not a substitute for killing a production container
or filling a real filesystem.
