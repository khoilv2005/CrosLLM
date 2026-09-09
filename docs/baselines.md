# Baseline adapter boundary

`src/crossllm/baselines/external.py` provides the M07.01–M07.03 execution
boundary for native/conditioned tools. A `ToolSpec` identifies the executable
argv, upstream revision, config hash, supported scope, timeout, network policy
and declared CPU/memory/PID envelope. The adapter records stdout/stderr hashes
and elapsed time, preserves raw JSON findings, and returns explicit
`UNSUPPORTED`, `TIMEOUT` or `CRASH` statuses.

An empty finding list becomes `BOUNDED_UNSAT` only after the command exits
successfully and its output parses. Missing binaries, nonzero exits and
malformed output never become a clean no-finding result. Normalization preserves
tool-native fields and does not add CrossLLM-specific dictionaries.

The resource envelope is marked `declared_only` in every result: the adapter
enforces its wall-clock timeout, while CPU/memory/PID enforcement must be
attested by the outer container/worker. This is an adapter contract and
smoke-tested subprocess boundary. It does not yet prove upstream algorithm
fidelity, owner-accepted native support matrices, or conditioned semantic equivalence.
Those remain open M07 evidence items before calibration.

`baselines/support.py` adds a hash-addressed support matrix. An owner-accepted matrix
requires owner/date and evidence hashes for every tool/scope entry; unknown
or unsupported scope stays visible. Its coverage report keeps unsupported rows
in the operational denominator.

`baselines/subset.py` and `scripts/select_baseline_subsets.py` add an
outcome-blind selector for the 48-instance baseline/ablation and 24-instance
sensitivity subsets. It uses only configured instance/lineage/family,
pre-outcome positive/negative strata and optional architecture fields,
guarantees requested minimum coverage when the population permits it, records
the seed, population hash, IDs and counts, and refuses to overwrite an existing
selection record. Optional static method eligibility produces common-supported
IDs and operational coverage without filtering unsupported instances out of the
denominator. Running it on the current structural benchmark writes a proposed
selection only; it is not an evaluation freeze or admission evidence.

`baselines/sensitivity.py` enumerates the M07.07 Cartesian matrix: proposal
prefixes, transaction/channel bounds, solver timeout, horizon, FIFO/reordering,
bounded pre-finality reorg, challenge timing, attestation profile and program
size. Every cell carries method/track, explicit budget and `pending`, `eligible`
or `unsupported(reason)` eligibility. `analysis/proposal_recall.py` keeps the
stored ordered-batch proposal recall@N endpoint separate from scheduled
end-to-end recall under budget N; missing archives/outcomes remain missing.

`scripts/run_sensitivity_matrix_rehearsal.py` materializes the current
prespecified development contract as 13,824 cells (X/P × automatic track) and
records the matrix hash plus per-method coverage at
`dataset/reports/m07_sensitivity_matrix_rehearsal.json`. The rehearsal keeps
all cells `pending`; no method outcome, native-tool eligibility, or evaluation
denominator is inferred from the Cartesian expansion.

`scripts/run_baseline_and_recall_rehearsal.py` exercises the registered
48-instance baseline/ablation shape, the 24-instance Qwen/gpt-oss sensitivity
shape, and both M07.08 recall endpoints. Its reports are
`dataset/reports/m07_selection_rehearsal.json` and
`dataset/reports/m07_recall_rehearsal.json`; both are outcome-blind synthetic
development artifacts and cannot satisfy evaluation admission.

`methods/ablation.py` records the five P0 primary contrasts and a separate
post-primary gold diagnostic. It rejects an arm pair that changes more than the
declared component, requires shared input names for paired controls, and
disallows gold access in primary arms.

`baselines/gptscan.py` requires a declared learned-component inventory and
labels an Ollama substitution as `transparent_adaptation` unless an audit
proves faithful retention. `baselines/conditioned.py` carries independent
property, common semantic harness, track-model and storage-model hashes, plus
separate effort counters for conditioned H0/H1/F0/O0 runs. Neither contract
pretends to be upstream algorithm or semantic-harness evidence until the pinned
tool runs are supplied.
