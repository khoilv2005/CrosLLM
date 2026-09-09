# M00.02 Backend feasibility spike

Date: 2026-09-08
Status: `PARTIAL`; decision: `NO-GO_FOR_G2`

## Scope

The spike checks whether the current development foundation exposes the
interfaces required before investing in a full symbolic/EVM backend:
snapshot/restore, transaction stepping, symbolic storage bindings, channel
actions and witness extraction.

## Evidence available

| Capability | Evidence | Result |
|---|---|---|
| Snapshot/restore | `tests/unit/test_paired_fixture.py`, `dataset/reports/backend_feasibility_spike.json` | Passes for chain, pending channel, storage/observer state and deep restore |
| Transaction/channel stepping | `TransitionBounds`, `ActionRecord`, paired fixture tests, `backend_feasibility_spike.json` | Passes on bounded enqueue/deliver/reorg sequences with separate transaction/channel indices |
| Channel scheduling | `tests/unit/test_paired_explorer.py` | Passes SAT, exhaustive `BOUNDED_UNSAT`, state-limit `UNKNOWN`, reorder and reorg profiles |
| Symbolic storage bindings | `src/crossllm/xlir/lowering.py`, `src/crossllm/xlir/evaluator.py`, `backend_feasibility_spike.json` | Grounded bytes32 storage binding, typed concrete evaluation and solver-neutral lowering pass; no symbolic EVM state engine |
| Witness extraction | `src/crossllm/replay/witness.py`, `backend_feasibility_spike.json` | Symbolic SAT → indexed witness → native replay and hash/sequence validation pass |
| Independent EVM replay | `src/crossllm/replay/evm.py`, `docs/evm_replay.md`, `docs/evm_support_matrix.md` | Subprocess boundary, immutable digest validation, explicit statuses, IO hashes and hash-verified support-matrix contract are tested; a Celer draft matrix, real pinned-host Foundry replay (3/3), and a three-case structural-only symbolic-to-source correspondence report now exist, but no reviewed host matrix, direct trace comparison, or independent Q evaluator exists |
| Solver execution | `z3-solver==5.1.0.0`, Z3 `5.1.0`, imported on CPython 3.14.7; `src/crossllm/backends/smt.py` | Quantifier-free grounded XLIR core available; dual-chain integration not available |

The latest implementation suite has 397 passing tests and the tool suite has 19
passing tests. These tests establish contract behavior only; they do not prove
that a source-pinned bridge implementation, proxy, bytecode or initialization
state agrees with the fixture.

## Decision and unsupported scope

The fixture explorer is acceptable for G1 development mechanics and differential
test scaffolding. It is not sufficient for G2 calibration or G3 evaluation. The
  following remain explicit blockers:

- review the symbolic paired-transition integration with the pinned SMT backend
  and expose transition-level completeness, timeout and cancellation for the
  admitted host/profile matrix;
- implement an independent EVM replay adapter using exact source/build/
  initialization artifacts;
- independently review the opcode/precompile/proxy/crypto support matrix
  defined at `src/crossllm/replay/support.py` and materialized for all three
  development hosts at `dataset/reports/evm_support_matrix_*.json`;
- complete a symbolic-to-concrete differential spike on at least one approved
  source-pinned development host. `dataset/reports/symbolic_to_source_differential.json`
  now records three structural correspondences and explicit unsupported
  semantics, while the aggregate source-backed Foundry replay receipt records
  Celer 3/3, ChainBridge 5/5 and LayerZero v2 5/5 native workflow tests. This
  remains non-admission because traces are not directly comparable and no
  independent Q evaluator is attached.

The M00.02 follow-up report `dataset/reports/backend_feasibility_spike.json`
passes all five requested development capabilities: snapshot/restore,
transaction stepping, grounded symbolic storage, FIFO/reordering/reorg channel
actions and witness extraction. It records the exact fixture/profile hashes and
unsupported EVM semantics, but remains non-admission because the paired fixture
is not a source-level EVM execution trace.

An SMT `BOUNDED_UNSAT` result is currently evidence only for the finite XLIR
formula (including explicitly expanded finite quantifiers/temporal operators)
that was encoded. A fixture or SMT result is not
evidence about a real host until the transition encoding, exact host artifacts,
and independent replay conditions are satisfied.
