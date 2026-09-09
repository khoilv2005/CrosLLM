# ADR M00.03 — Backend boundary and feasibility decision

Date: 2026-09-09  
Status: `PARTIAL`; development decision recorded, owner acceptance pending.  
Decision: `GO_FOR_G1_DEVELOPMENT`, `NO-GO_FOR_G2/G3_EVALUATION`.

## Context

The implementation plan requires a decision before the repository treats a
solver wrapper as a CrossLLM engine. The current evidence combines:

- a bounded paired-chain fixture and a Z3 symbolic transition encoding;
- native witness projection/replay with explicit tamper and unsupported states;
- a digest-pinned Foundry subprocess boundary;
- a source-backed Celer development harness and a 3/3 native EVM replay; and
- a three-case symbolic-to-source correspondence report.

The correspondence report is deliberately `structural_only`: the fixture's
enqueue/deliver/reorg actions are not a byte-for-byte or storage-equivalent
trace of Celer's transfer-out/transfer-in/confirm/refund workflow. The current
source replay also has no independent Q/property evaluator.

## Decision

### 1. Backend split

The backend has two explicit layers:

| Layer | Allowed role | Evidence boundary |
| --- | --- | --- |
| `PairedFixture` + `SymbolicPairedExplorer` | G1 mechanics, finite scheduling, witness/search contract and development differential scaffolding | `src/crossllm/semantics/`, `src/crossllm/backends/`, `tests/unit/test_symbolic_paired.py` |
| `FoundryDockerReplay` / independent EVM adapter | concrete source/build/initialization replay in a separately identified process | `src/crossllm/replay/foundry.py`, `docs/evm_replay.md`, source-backed Celer receipt |

No result from the first layer is a security claim about the second layer.
The readiness gate requires both layers plus an owner-accepted host support matrix,
an independent Q evaluator, a witness checker, and a direct differential
report for every admitted host/profile configuration.

### 2. hevm modification scope

Do not fork or modify hevm in the current development phase. The repository
does not yet have evidence that hevm's supported EVM version, bridge-specific
initialization, proxy behavior, or cross-domain environment can represent the
admitted hosts. A future hevm adapter may be evaluated only after an owner-accepted
support matrix and a differential test suite demonstrate that its state,
environment, and trace projections agree with the independent EVM adapter.

### 3. Adapter boundary

An independent adapter must accept a hash-bound replay specification containing
the exact source/artifact/build/initialization/profile identities, immutable
tool/container identity, network policy, timeout and witness input. It must
return an explicit status, exit code, stdout/stderr hashes, optional trace hash,
and a machine-readable source-level observation. The adapter must not invoke a
shell, broadcast transactions, mount private gold, or download model weights.

The current `EVMReplaySpec` and `FoundryReplaySpec` implement the process and
identity boundary. They are not yet sufficient for admission because the
source-level observation and independent Q evaluator are still absent.

### 4. Dependency and license policy

Python runtime dependencies are installed from hash-pinned
`requirements.lock`; Windows development uses Z3 `5.1.0.0`, while Linux CI
uses the pinned manylinux Z3 `4.15.4.0` variant. Solidity compilers and Foundry
are referenced by immutable container digests in `containers/`. Native EVM
execution remains containerized and no-network by default.

Dependency and component license records remain provenance inputs, not an
automatic admission decision. The source-cache/license audit and the project
owner's acceptance record must cover the exact selected source components
before G2. This follows the single-owner-plus-Codex workflow policy; it is not
independent review.

### 5. Go/no-go consequence

The repository may continue G1 fixture development, contract/schema tests,
provider fake/archive tests, and source-backed development probes. It must not
start G2 calibration or G3 evaluation, publish a confirmed vulnerability, or
mark a structural correspondence as an independent differential result until
the open gates below are satisfied.

## Required exit evidence

1. An owner-accepted support matrix for each admitted host/profile, including
   opcode, precompile, proxy and cryptographic scope.
2. A direct symbolic-to-concrete differential report with matching state/action
   projections and an independent Q evaluator, including deliberately wrong
   property and altered-witness controls.
3. Clean-worker installation and tool/container identity evidence bound to the
   runtime lock.
4. Source/build/initialization/trigger/control evidence for the benchmark
   corpus, plus an owner acceptance record and explicit single-operator
   limitation.

Until these are present, this ADR is a development decision record only. It
does not satisfy M00.03/M00.04 acceptance or G3.01.
