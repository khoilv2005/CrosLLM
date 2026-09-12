# Across source-backed executable adapter

The first-party adapter is `scripts/source_executor.py`. It consumes only the
grounded XLIR runtime request produced by `RuntimeCandidateAdapter` and the
clean workspace materialized by `SourceBackedVerificationExecutors`. It does
not read mutation patches, property assessments, trigger-validation receipts,
or any other gold/admission artifact.

The current executable profile is intentionally narrow:

- lineage: `across`;
- workflow: isolated `setUp` followed by the source-backed normal
  `depositV3`/fast-fill workflow;
- predicate: non-temporal XLIR state expressions whose symbols have a bound
  scalar storage slot or a checked public getter;
- search: one finite, candidate-specific Foundry execution, reported as
  `sat` when the candidate predicate is false and `bounded_unsat` when it
  holds on that declared workflow;
- witness check and replay: the same predicate is regenerated and executed in
  separate clean case workspaces.

This is a real source-backed bounded execution adapter, not a general EVM SMT
solver. Temporal predicates, quantifiers, unsupported storage types, and
lineages without an explicit profile remain `unsupported`.

## Local setup

The Foundry image is deliberately run without network access. Across pins
Solidity `0.8.30`, so provision a compiler volume from the locked compiler
image before invoking the adapter:

```powershell
$env:PYTHONPATH = "src"
$env:CROSSLLM_COMPILER_VOLUME = "crossllm-solc-<prepared-volume>"
```

The volume must contain `/compiler/solc` with the locked `0.8.30` binary. The
repository helper is used by the development probes:

```powershell
$env:PYTHONPATH = "src"
python -c "from dataset.tools import extract_all_artifacts as e; v=e.create_compiler_cache_volume('source-across'); print(v); print(e.populate_compiler_cache_volume(v,'0.8.30'))"
```

Then set `CROSSLLM_COMPILER_VOLUME` to the printed volume name and use the
pinned executor bundle:

```powershell
$env:CROSSLLM_SOURCE_PHASE_TIMEOUT_SECONDS = "300"
python scripts/run_verification_stage.py `
  --repo-root . `
  --archive-root crossllm=<proposal-archive-root> `
  --manifest dataset/benchmark/benchmark.public.jsonl `
  --source-executors configs/source_executors_across.json `
  --out <verification-output.jsonl>
```

An absent compiler volume is a toolchain failure, not a negative result. A
60-second probe is also insufficient for an uncached Across build; the profile
uses a 300-second phase timeout and retains explicit `foundry_build_timeout`
or `foundry_test_timeout` reasons.
