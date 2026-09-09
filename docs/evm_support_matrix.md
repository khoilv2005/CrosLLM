# EVM execution support matrix

`EVMExecutionSupportMatrix` is the explicit boundary between the XLIR/native
model and an independent EVM replay host. Entries are scoped to opcodes,
precompiles, proxy behavior, or cryptographic operations and use one of four
states: `supported`, `conditional`, `unsupported`, or `unknown`.

The matrix hash is included in `EVMReplaySpec` when a host acceptance exists. A
`draft` matrix is useful for development diagnostics but cannot satisfy the
evaluation readiness gate. `owner_accepted` additionally requires the project
owner, acceptance timestamp, Codex self-check and evidence hashes; the evidence
hash points to the host-specific support proof. No second reviewer is required
by the current workflow policy.

The repository now contains a source-backed development draft for the locked
Celer host at
`dataset/reports/evm_support_matrix_celer_cbridge.json`.  It is derived from
the Celer deployed-bytecode opcode scan plus the locked source, artifact and
channel-profile hashes.  The matrix is bound into
`dataset/reports/source_backed_replay.json`, so a replay receipt cannot silently
change scope.

The matrix is intentionally `draft`, marks unobserved precompiles/opcodes as
`unknown`, and marks generic proxy resolution as `conditional`.  It is not a
reviewed host matrix and does not contain an independent Q evaluator or a
symbolic-to-concrete differential report; therefore `G3.01`/`M00.04` and
evaluation admission remain pending.
