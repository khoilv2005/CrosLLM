# Witness projection and replay boundary

The current implementation covers the native, in-memory fixture boundary for
M05.01 and M05.02. `WitnessProjector` accepts only a complete `SAT` result,
replays its action evidence from the initial fixture, and emits:

- an initial-state hash covering chain state, channel state, clocks, observers,
  canonical history and action log;
- a trace hash over the ordered transaction/channel actions;
- explicit domains, proof-object metadata and allowed-capability metadata;
- `native_replay_status` and `independent_replay_status`; the latter remains
  `unknown` until a real pinned-host adapter run is available. The repository
  now provides the separate subprocess boundary in
  `src/crossllm/replay/evm.py`, but that boundary has no admitted EVM result.

`NativeReplay` decodes action fields strictly, including message string types,
uint256 nonce bounds, non-negative indices and rejection of unknown fields;
resolves delivery by message identity, checks transaction/channel indices,
verifies both hashes and rejects missing or infeasible actions. The standalone
`schemas/witness.schema.json` mirrors this public boundary and is exercised in
unit tests. It uses the same deterministic fixture as the search backend, so it
is a development differential helper rather than independent evidence of EVM
correctness.

The independent subprocess boundary also validates artifact, initialization and
profile identity hashes. An adapter result is not accepted as `PASS` unless it
contains a lowercase SHA-256 trace hash; malformed or missing trace evidence is
reported as `UNKNOWN`.

`assess_witness` is the M05.04 state machine for combining these facts. It
keeps model-trace validity, native replay, independent replay, security
relevance and allowed capabilities as separate fields. Only a complete set of
positive checks yields `confirmed`; `UNKNOWN`/`UNSUPPORTED` remains
`pending`, and hard replay/capability failures are `rejected`. Native
witness time and independent evaluator reproduction time are stored separately.

This does not satisfy M05.03–M05.06 or the M04/M05 acceptance gate. The remaining
requirements are exact pinned initialization/bytecode replay on an independent
EVM, deliberate tamper/incorrect-property cases against that replay, and
separate native-witness/evaluator reproduction timing in runtime records.
