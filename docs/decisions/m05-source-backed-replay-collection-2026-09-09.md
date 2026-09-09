# M05 source-backed replay collection

Date: 2026-09-09
Status: `DEVELOPMENT EVIDENCE ONLY`

## Decision

Use one shared `FoundryDockerReplay` boundary for the three source-backed
development harnesses. Each receipt must bind the source manifest, primary
source file, artifact manifest, deterministic deployment configuration, channel
profile, compiler binary/image, Foundry image, and a host-specific EVM support
matrix. The container uses a read-only source mount, a read-only compiler
volume, dropped capabilities, and `network_mode=none`.

The aggregate receipt is
`dataset/reports/source_backed_replays.json`. The host matrices are:

- `dataset/reports/evm_support_matrix_celer_cbridge.json`
- `dataset/reports/evm_support_matrix_chainbridge.json`
- `dataset/reports/evm_support_matrix_layerzero_v2.json`

The observed native harness results are Celer cBridge `3/3`, ChainBridge
`5/5`, and LayerZero v2 `5/5`. `scripts/run_source_backed_replays.py --check`
and the strict dataset validator verify the receipt and all hash bindings.

## Boundary and limitations

The LayerZero paired harness executes the checked-in `EndpointV2` source and
its Foundry output. Its separate artifact pack is centered on `SendUln302`; the
support matrix therefore records the actual harness bytecode path rather than
silently pairing `SendUln302` bytecode with `EndpointV2` source.

This evidence proves successful native development-harness replay only. It
does not prove that a symbolic trace is directly comparable to an EVM trace,
that Q/property/trigger labels are independently correct, or that any case is
admitted. All matrices remain `draft`, and all replay receipts explicitly set
`independent_evaluator`, `independent_property_validation`,
`independent_trigger_validation`, and `admission_eligible` to `false`.

## Follow-up required before M05/G3 acceptance

1. Attach an independently reviewed support matrix for every admitted host.
2. Emit a directly comparable symbolic-to-EVM trace with an independent Q
   evaluator and tampered/wrong-property controls.
3. Bind the replay to admitted mutation, gold, trigger, and matched-control
   records after independent review.
