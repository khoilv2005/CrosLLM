# Runtime events, resume and resource scheduling

The runtime layer now has two explicit boundaries:

- `src/crossllm/runtime/events.py` stores immutable lifecycle events as JSONL,
  rejects duplicate event IDs and terminal attempts, and reconstructs a campaign
  attempt after restart. A completed attempt cannot be resumed as a new
  replicate. A lost response or worker restart is recorded as `uncertain` and
  resumes with the same `attempt_id`; version drift is blocked by policy.
- `src/crossllm/runtime/resources.py` models one worker with the protocol default
  of 4 CPU cores and 16 GiB RAM. Declared campaign allocations are admitted only
  when aggregate CPU/RAM, concurrency, solver-profile exclusivity and cumulative
  quota permit them. Estimates are reserved while a lease is active, and a FIFO
  queue is drained after measured usage is released.

`ResourceUsage.as_resource_vector()` follows the existing runtime schema. Missing
provider token measurements remain `null` with a reason; they are not converted
to zero. `ResourceObservation` reports CPU/RAM envelope violations, but Python
admission is not a substitute for cgroups or container limits. M08.02/M08.04
therefore remain engineering-partial until a worker process/container applies
these limits and the offline crash/restart rehearsal passes.

The unit coverage is in `tests/unit/test_runtime_events.py` and
`tests/unit/test_runtime_resources.py`.

`runtime/isolation.py` adds explicit checks for public/controlled mounts,
disabled private-gold access, no-broadcast EVM execution and provider egress
allowlisting. `runtime/canary.py` freezes model/protocol/prompt/toolchain
identity; a mismatch or failed canary is `blocked`, and only an explicit,
evidence-backed deviation is recorded as `deviation`. These are policy records,
not a claim that the current Windows host has already enforced container ACLs.
`DockerWorkerCommandBuilder` now emits `--network=none` for offline workers;
provider workers use an explicit bridge mode and carry the hostname allowlist,
but still require an external firewall/proxy because Docker bridge networking
does not enforce hostname-level egress policy.

`runtime/runner.py` now provides the development execution boundary. A batch of
`WorkerTask` values is admitted through the quota-aware scheduler, executed with
bounded concurrency, and returned in the original plan order. Each admitted
task gets a planned/running/terminal event sequence; an explicit uncertain
worker failure can resume with the same `attempt_id`, while a terminal campaign
is never silently resampled. The runner records measured wall/CPU usage and
queue/throttle telemetry, and emits explicit `UNSUPPORTED` records for work
that cannot be admitted after active leases drain.

`runtime/method_events.py` projects each `MethodRun` into an auditable event
sequence: one `method_started`, one `provider_response` and one
`proposal_slot_recorded` for every ordered slot, followed by `method_completed`.
The projection retains raw provider archive fields and slot status/hash
correspondence, rejects credential-shaped fields, and is used by the offline
dry-run. It is an event projection for runtime auditing, not evidence that a
remote provider or a production container has been executed.

The event validator also requires terminality to be final for each attempt: a
non-terminal event after `campaign_terminal` is rejected instead of being
silently ignored during restore.

This is still a portable callback runner, not proof of host isolation. The
production entry point must execute the same task inside the digest-pinned
Docker command from `runtime/worker.py`, with cgroups enforcing the declared
4-core/16-GiB envelope. Unit coverage for the orchestration boundary is in
`tests/unit/test_runtime_runner.py`.

For restart safety, `PersistentEventStore` commits every event before exposing
it in memory; `WorkerRunner` restores existing uncertain attempts and refuses
to invoke a terminal campaign again, including when a caller supplies a new
attempt ID for the same campaign.
