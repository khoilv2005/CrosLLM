# Dataset status ledger

## Current verified progress

This ledger distinguishes canonical admission evidence from files that have been generated in the repository. Artifact packs, structural manifest validation, stored trace fixtures and a commitment receipt do not by themselves admit a benchmark case. See `../../docs/current_status.md` for the repository-wide assessment dated 2026-09-09.

| Gate | Count | Status |
|---|---:|---|
| Historical candidate records | 6 | Candidate inventory only |
| Historical cases admitted to evaluation | 0 | Not started: requires artifact, replay and control evidence |
| Locked protocol lineages | 16 | Complete initial partition: 4 development, 12 evaluation |
| Source snapshots retrieved and content-hashed | 4 | Hop, LayerZero V2, Celer cBridge and ChainBridge are the `source_pinned` entries in the canonical lock/receipt records; this is not case admission |
| Artifact packs with local manifest/checksum | 16 | Generated ABI/bytecode/layout packages; local checksums verify package integrity, not source admission or deployability |
| Generated paired-harness projects and trace fixtures | 16 | Harness code exists, but generated mock-based workflow tests have not established replay of the exact pinned production contract paths |
| Structurally validated proposed benchmark rows | 240 | 120 sealed/vulnerable + 120 negative/patched rows; structural validation does not establish semantic ground truth |
| Sealed validated positives | 0 | No independently admitted mutation, source patch, property and trigger evidence in the canonical admission ledger |
| Distinct matched negative controls | 0 | No independently admitted matched-control evidence in the canonical admission ledger |
| Evaluation-ready cases | 0 | No experiment may be run yet |

## Blocking gates

The dataset will remain non-evaluable until every selected case has a source/bytecode/proxy configuration, reproducible paired harness, independent property and trigger validation, and a matched clean control. The target counts in the experiment guide are not substituted with repeated mutants, contract dependencies, or variants from the same lineage.

The mechanical review artifact `../reports/historical_candidate_reviews.jsonl` now
covers all six historical records. It is deterministic, source-registry-bound and
fail-closed: all six remain `candidate` with `admission_eligible: false`, and the
Anyswap/Multichain records are explicitly marked as sharing one lineage. It is not
a substitute for independent evidence or human review.

The source-backed development mutation receipt `../reports/source_mutation_evidence.jsonl`
records 2/2 passing Celer `CBridge` control/mutant probes for replay and finality.
The runner uses the locked source manifest, digest-pinned Foundry, locked `solc 0.8.9`
and `network_mode: none`. Both rows deliberately remain non-admission and do not claim
independent property or trigger validation.

The independent replay receipt `../reports/source_backed_replay.json` records a
3/3 passing native EVM replay of the exact Celer source-backed harness. Its
artifact, deployment, profile, source and compiler identities are hash-bound;
the receipt also binds the draft support matrix
`../reports/evm_support_matrix_celer_cbridge.json`; it remains
development-only because native assertions are not an independent Q evaluator
and no evaluation case is admitted.

The aggregate receipt `../reports/source_backed_replays.json` extends the same
hash-bound, network-isolated replay boundary to all three source-backed
development harnesses: Celer 3/3, ChainBridge 5/5, and LayerZero v2 5/5. The
two additional host matrices are
`../reports/evm_support_matrix_chainbridge.json` and
`../reports/evm_support_matrix_layerzero_v2.json`; both remain draft and require
independent review/differential evidence.

The development replay negative-control receipt
`../reports/replay_negative_controls.json` records 6/6 pass for deliberate
wrong-property, altered-witness, infeasible-action, wrong-initial-state,
ordering and patched-control checks. It is boundary evidence only: it does not
provide independent gold/property/trigger labels for evaluation admission.

The Docker isolation canary `../reports/isolation_canary.json` records 6/6
development checks: public sentinel execution in a digest-pinned,
read-only/network-none container; rejection of private gold and model-cache
mounts; Ollama-only provider allowlisting; and broadcast rejection. Provider
egress still requires an external firewall rule, so this is not an evaluation
readiness certificate.

The calibration rehearsal `../reports/m10_development_calibration_rehearsal.json`
exercises the M10 menu, ten-call-per-setting fixture, truncation diagnostics,
hierarchical precision/common-R selection, budget estimate and development
freeze hashes. It records `executed_provider_calls: 0`, uses synthetic
probabilities, selects no common R under the declared precision targets, and
is therefore planning evidence only.

The M06 provider-contract rehearsal `../reports/m06_provider_contract_rehearsal.json`
records 9/9 synthetic cases with 53 fake transport calls and zero Ollama Cloud
calls. It covers raw capture/archive, retry and cancellation controls, all
ordered proposal-slot outcomes, token/budget boundaries, four-family preflight,
and shared X/P/T0 prompt/settings. It is non-admission and does not attest to
served model identity, quota, checkpoint stability or live outcomes.

The M08.07 canary/version rehearsal `../reports/m08_canary_version_rehearsal.json`
records 4/4 synthetic cases: matching identity passes, failed panels block,
identity drift blocks, and explicit deviations are recorded separately. It has
zero provider calls and is non-admission evidence only.

The M08.08 runtime rehearsal `../reports/m08_development_runtime_rehearsal.json`
hash-binds its raw event and fault-event JSONL exports. The stable summary
validates 58 total events, 54 method events, same-attempt resume, 12 fault
events, and 24 synthetic provider calls with zero Ollama Cloud calls. It is
offline development evidence only.

## Next construction batch

1. Finish source pinning for the four development lineages.
2. Build a local paired EVM harness and compiler/differential-execution checks for each.
3. Define development-only mutation operators and matched control construction.
4. Use development results to lock mutation/harness policy.
5. Repeat acquisition on the twelve evaluation lineages without changing prompt/model settings.
