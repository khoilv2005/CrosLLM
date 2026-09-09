# M11 Hop source-backed development probe

Date: 2026-09-10  
Status: `PASS_FOR_DEVELOPMENT_PROBE_ONLY`

## Scope

The Hop harness now compiles the exact locked source closure from
`hop-protocol/contracts` at commit
`0726ffa0e14745134116e552178fd7e0edcfa8e6`. The upstream bridge contracts are
abstract, so the probe targets the exact upstream `Mock_L1_Bridge` and
`Mock_L2_Bridge` test wrappers while preserving the logical artifact names
`L1_Bridge` and `L2_Bridge`.

## Evidence

- source archive SHA-256:
  `054ce4a64cadd40732987268d628c76ca63cbd036c31323c0b774595ee2f87c4`
- artifact selection SHA-256:
  `78fb4e9d88be9911caa190d9bcb114bfa68c1871ca6c926999afcec01897d617`
- source manifest SHA-256:
  `6897a0b5896032092137a8c2926ae7624fc1e3a9ae6fd8a8006a05eb6a2a2409`
- probe row SHA-256:
  `c2d9901bdb9a3167d1b51663f7cc4a085bb16c8a478c1a63ad3b132f1493b82b`
- Foundry image:
  `ghcr.io/foundry-rs/foundry@sha256:0c00cb0bda1ab1b91c9a6bf60f4c76c09c1a8870824b6d4718afbabacf6f9a17`
- solc image:
  `ghcr.io/argotorg/solc@sha256:ba8da496fd063c7dddb2282f115b2a59c5deaf8f2ab06a4ca858304fedaeb5c9`
- compiler: `/compiler/solc`, version `0.6.12`, binary SHA-256
  `fab8f0275c8e6111294431eb7ddc03c12625a62b26e38f36a5ece659370f977b`
- execution: network `none`, read-only source/compiler mounts, 5/5 tests passed

## Decision and limitation

The probe is promoted to `source_backed_development`; the artifact receipt is
`source_pinned_and_built`. This does not admit any evaluation case. Ancestry,
mutation/negative-control evidence, independent replay, owner acceptance and
the final evaluation locks remain separate gates. The workspace has one owner
and Codex; no second reviewer is asserted.
