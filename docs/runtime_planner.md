# Campaign planner and runtime boundary

`src/crossllm/runtime/planner.py` implements the M08.01 planning boundary.
It expands instance × method × backbone × replicate combinations, validates
unique lineage/instance inputs, derives stable UUID5 campaign IDs from frozen
inputs, randomizes only the scheduled order with a recorded seed, and hashes the
ordered campaign records.

Development plans can be generated with a positive replicate count. Evaluation
plans additionally require protocol, model and benchmark lock hashes; a
prospective planning file cannot silently become an evaluation plan. The
planner can write one campaign record per JSONL line or a complete JSON plan
artifact. The complete artifact retains plan metadata and lock hashes required
by readiness checks; neither format is an execution result.

The complete JSON artifact also contains `plan_hash`, computed over the unsigned
metadata and campaign list. Evaluation readiness verifies this hash and checks
that protocol/model/benchmark references agree with the corresponding lock and
evidence artifacts; a JSONL stream without plan metadata is therefore not an
evaluation lock by itself.

The package CLI exposes the same boundary for development or locked evaluation
inputs:

```bash
crossllm plan --mode development --instances instances.jsonl \\
  --methods X,P --backbones backbones.json --replicates 1 --seed 7 \\
  --config protocol/protocol.json --out build/campaigns.plan.json
```

The adjacent runtime boundaries are implemented at development-test level:
`runtime/events.py` provides append-only lifecycle events, uncertain interruption
states, JSONL restore and a fixed same-attempt resume policy; `runtime/resources.py`
provides a 4-core/16-GiB envelope, quota-aware FIFO admission, one solver lease
per profile and resource observations. See `docs/runtime_events.md`.

M08.02 and M08.04 are still partial: process/container enforcement, durable
crash-safe writer semantics and full provider-outage/fault rehearsal remain
before G1. Isolation, telemetry, canary/version blocks and the fixture-only
pipeline rehearsal are covered by development boundaries.
