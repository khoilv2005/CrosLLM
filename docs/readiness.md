# Evaluation readiness checker

`crossllm readiness --mode evaluation` runs the conservative gates mapped to
G3.01--G3.10 in `docs/implementation_plan.md`. Missing evidence is
`PENDING`; an explicit negative assertion is `FAIL`. The command exits with
code `3` unless every gate is `PASS`.

The checker requires an evaluation protocol lock, four preflighted model
families, an evaluation-locked toolchain, a hash-linked campaign plan, a
owner-accepted, hash-verified backend support matrix plus independent EVM differential
evidence, admitted positives/controls and the runtime/analysis/adjudication
rehearsals. Model records must also preserve requested tag, license/source
evidence and an explicit limitation when served identity is not immutable. It does not infer these facts from
file names or from structural benchmark validation.

Development probe:

```bash
crossllm readiness --mode development
```

Evaluation gate:

```bash
crossllm readiness \
  --mode evaluation \
  --protocol protocol/locks/protocol.lock.json \
  --models protocol/locks/models.lock.json \
  --toolchain containers/toolchain.lock.json \
  --plan protocol/locks/campaigns.plan.json \
  --evidence protocol/locks/evidence.index.json
```

The current workspace intentionally returns not-ready because its protocol is
prospective, its toolchain is a development probe, no campaign/evidence lock
is present, and independent EVM/corpus gates are not admitted.

## Evaluation launch boundary

Immediately before a future evaluation runner makes its first provider request,
call the side-effect-free launch check:

```bash
crossllm evaluation-launch-check \
  --protocol protocol/locks/protocol.lock.json \
  --models protocol/locks/models.lock.json \
  --toolchain containers/toolchain.lock.json \
  --plan protocol/locks/campaigns.plan.json \
  --evidence protocol/locks/evidence.index.json \
  --report-out build/evaluation-launch-report.json
```

The command recomputes the readiness report hash, requires `evaluation` mode,
requires every readiness gate to be `PASS`, and rejects plans explicitly marked
development/non-admissible. It starts no provider calls and exits `3` when the
boundary is not satisfied. A real evaluation executor must call the same
`EvaluationLaunchGuard.assert_ready()` API before creating its first request;
passing a CLI flag cannot override the guard.

`EvaluationRunner` is the execution-side wrapper for this contract: it invokes
the guard before delegating any task callback to `WorkerRunner`. Development
rehearsals continue to use `WorkerRunner` directly and remain non-admission.
The wrapper also requires every submitted campaign ID to exist in the locked
campaign plan.

`crossllm protocol-lock` is the offline materialization boundary for the
protocol dependency. It requires a positive evaluation replicate count, an
empty `missing_execution_fields` list, and 64-hex hashes for the model lock,
benchmark manifest and optional dependencies. With the current prospective
`protocol/protocol.json`, it exits nonzero and writes no lock file.
