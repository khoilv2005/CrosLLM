# Independent EVM replay boundary

`IndependentEVMReplay` is the M05.03 subprocess boundary. It executes a
separately identified command without a shell, requires an immutable
`container_ref` digest, binds artifact/initialization/profile hashes into the
specification, captures stdout/stderr/trace hashes, and preserves missing
binary, timeout, malformed-output and nonzero-exit states. A successful
adapter must emit JSON with an explicit replay `status` and may emit a
64-character `trace_hash`. A `cancelled` callback is propagated to the
subprocess boundary and terminates the child process; cancellation and timeout
remain explicit non-success statuses.

The replay command may use the exact argument placeholder `{workspace}`. For a
source-backed candidate run this is a fresh case workspace containing the
locked source and paired test; it is different for search, witness checking
and replay. This keeps replay from reusing symbolic process state while
allowing a real adapter to locate the case-local harness.

The boundary has deterministic subprocess tests. It is not yet independent
EVM evidence: that still requires a real source-pinned adapter run over the
admitted contract initialization/bytecode, deliberate wrong-property and
tampered-witness cases, an independent evaluator for Q, and separate
native-witness/evaluator reproduction timing in runtime records.

`FoundryDockerReplay` is the concrete Docker/Foundry command boundary for that
future adapter. It pins the image digest, source-mounts the project read-only,
uses `--network=none` by default, drops capabilities, and parses explicit
`forge test --json` test statuses. For a no-network replay, callers can provide
`compiler_volume` together with its digest-pinned `compiler_image_ref`; the
command mounts the pre-populated volume read-only and invokes
`--use /compiler/solc`, so it does not rely on SVM/TLS compiler discovery. A
missing compiler is reported as
`UNSUPPORTED` when the compiler is explicitly unavailable offline, and
`UNKNOWN` when the compiler installer cannot be reached; neither is converted
into a successful replay. The current
development Foundry image does not embed solc, so compiler download requires a
separate development probe with bridge networking and an executable `/tmp`
tmpfs; this mode is explicitly not an evaluation isolation contract.

The aggregate development receipt at
`dataset/reports/source_backed_replays.json` runs the same boundary against all
three source-backed development harnesses: Celer cBridge (3/3), ChainBridge
(5/5), and LayerZero v2 (5/5). Each receipt binds its artifact, deployment,
profile, compiler, source, and host support-matrix hashes. The collection is
deliberately marked non-admission: native harness assertions are not an
independent Q/property/trigger evaluator.

## Independent property evaluation

`src/crossllm/replay/evaluator.py` supplies the concrete evaluator boundary
required after an adapter produces a normalized `SourceObservation`. Its
`PropertyEvaluatorSpec` binds evaluator revision, artifact, initialization,
profile and optional support-matrix hashes; the result keeps property hash,
source trace hash, observation hash and `PASS`/`FAIL`/`UNKNOWN` separate from
`security_relevance`. The evaluator calls the concrete XLIR evaluator directly
and does not invoke SMT lowering. Missing or invalid bindings produce
`UNKNOWN`, never a false property result. The boundary is covered by
`tests/unit/test_independent_property_evaluator.py`, but no source-backed
receipt is promoted merely because this interface exists.
