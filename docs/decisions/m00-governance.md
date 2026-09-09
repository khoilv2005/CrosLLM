# M00.05 Governance, private storage and deviation log

Date: 2026-09-09  
Status: `PARTIAL`; policy boundary implemented, owner acceptance pending.

The current workflow has only the project owner and Codex. The separate
reviewer/sign-off role described in the initial Experiment Guide is explicitly
skipped under `docs/decisions/m00-review-policy-2026-09-09.md`; records retain
the limitation instead of calling owner/Codex checks independent review.

## Roles and separation of duties

The implementation plan assigns the following responsibilities:

| Role | Responsibility | May approve evaluation admission? |
| --- | --- | --- |
| E — engine/formal methods | XLIR, transition semantics, solver and witness projection | Owner acceptance with Codex self-check; no second reviewer, and no independent-review claim |
| R — runtime/platform | provider transport, scheduling, persistence, workers and containers | No |
| B — benchmark | source builds, harnesses, mutations, properties and controls | No for its own gold or mutation decisions |
| A — analysis | estimands, simulations, statistics, tables and figures | No |
| J — adjudication | blinded labels, reconciliation and relabel history | No unilateral approval; reconciliation must preserve independent labels |
| Lead | dependency/deviation tracking and readiness decision | Project owner acceptance with Codex self-check; no second reviewer |

One person may hold multiple engineering roles during development. Because no
second reviewer is available, owner/Codex checks do not become independent
ground truth, validation or adjudication. High-risk records remain explicitly
limited until their source evidence and acceptance record are complete.

## Storage and worker boundary

| Class | Examples | Automatic worker access | Release rule |
| --- | --- | --- | --- |
| Public | sanitized artifact pack, public schema, proposal IDs | read-only | eligible for allowlisted export |
| Controlled raw | provider request/response bytes, execution traces, resource telemetry | write-only append or explicitly scoped read | release only after raw-data review |
| Private gold | mutation diff, exact trigger, gold property, adjudication labels | disabled | restricted storage; never mounted into a proposer/solver worker |
| Credentials | `.env`, `OLLAMA_API_KEY`, RPC credentials and private keys | provider worker environment only when explicitly authorized | never committed, copied into artifacts, or emitted in logs |

The policy implementation is `src/crossllm/runtime/isolation.py` and is tested
by `tests/unit/test_runtime_isolation_canary.py`. It blocks private-gold mounts
and broadcast-capable EVM execution, and only accepts an explicit HTTP(S)
provider host from the allowlist. Offline artifact/harness probes must use
`--network=none`; Cloud workers use only the Ollama Cloud endpoint
`https://ollama.com/api/chat` and do not download or mount local model weights.

The repository `.gitignore` excludes `.env` and the private benchmark manifest.
No credential value belongs in this record or in a public checksum.

## Deviation log

The following entries describe known deviations as of the date above. An entry
is not an approval; each remains open until its owner, evidence and acceptance
record are recorded.

| Deviation ID | Scope | Known state at decision time | Consequence | Owner | Acceptance/status |
| --- | --- | --- | --- | --- | --- |
| `DEV-M00-WINDOWS-DOCKER-001` | toolchain | Windows host has no native Foundry/solc; Docker server 29.7.2 is available | use digest-pinned Linux containers for development probes; host-specific replay remains pending | R | pending |
| `DEV-M00-SINGLE-OPERATOR-001` | roles | current implementation workspace has only project owner and Codex | no independent-review claim may be inferred from unit tests or generated fixtures; owner acceptance and limitation records are required | Lead | pending |
| `DEV-M00-HISTORICAL-INVENTORY-001` | historical cases | six records are public inventory leads; artifact, trigger, control and threat evidence are incomplete | retain `candidate`; exclude from results and commitment admission | B | pending |
| `DEV-M00-CLOUD-IDENTITY-001` | provider | Ollama Cloud transport is specified, but live served identity/effective settings are not yet attested | no runtime model lock or evaluation request is valid yet | R | pending |
| `DEV-HOP-ABSTRACT-TARGET-001` | Hop development lineage | locked target selection is abstract and not a deployable production contract | reject the substitution for source-backed artifact admission; preserve the deviation report | B | pending |

## Evidence and exit conditions

The policy boundary is evidenced by the isolation unit tests and the source
backed development harness Docker argv. The deviation log remains open until
the owner acceptance records and their evidence references are complete.
M00.05 therefore remains unchecked in `docs/implementation_plan.md`; this is
deliberate and prevents a documentation-only record from being mistaken for
completed governance.
