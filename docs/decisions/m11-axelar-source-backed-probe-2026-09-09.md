# Axelar Amplifier source-backed development probe — 2026-09-09

The Axelar Amplifier development harness now uses the locked
`AxelarAmplifierGateway` source and its exact local proxy, governance,
interface, library, type, and utility closure from commit
`30196ca7cb9479fd5f79f0668523bd2a488093ed`. The probe uses Solidity `0.8.36`,
the digest-pinned Foundry/compiler images, read-only source/compiler mounts,
and `network=none`.

The probe passed two tests: an outbound `callContract` plus weighted-signer
approval/consumption lifecycle, and rejection of an empty weighted proof. The
source-backed harness report and artifact metadata were finalized only after
the passing probe.

This remains development evidence, not evaluation admission. The profile uses
one deterministic signer and a local proxy/recipient adapter; it does not prove
the 120 real semantics-changing mutations, matched controls, independent
property/trigger evaluation, owner acceptance, or evaluation execution locks.
