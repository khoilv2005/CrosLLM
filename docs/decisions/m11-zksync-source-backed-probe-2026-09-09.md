# M11 zkSync Era source-backed probe

Date: 2026-09-09  
Status: `SOURCE_BACKED_DEVELOPMENT_PROBE_PASS`; not evaluation admission.

## Locked inputs

- Repository: `https://github.com/matter-labs/era-contracts.git`
- Commit: `ad5a4783a3f05b18049af62a2f31885ce4c70c3c`
- Source archive SHA-256: `506787b705b0f80fed3131199309fc0a0573ca5209027622e51fca34a3e794a9`
- Selected target: `l1-contracts/contracts/bridge/L1ERC20Bridge.sol`
- Compiler: `solc 0.8.28`, digest-pinned compiler image
- Foundry: digest-pinned image
- Probe network: `none`
- Harness mount: read-only source and compiler inputs

## Evidence

`ZkSyncEraSourceBackedHarnessTest` passed 3/3 tests. The harness uses the exact
locked source closure for `L1ERC20Bridge`, its selected interfaces/libraries and
the exact OpenZeppelin v4 dependency files required by `SafeERC20`. Generated
test support is limited to `MockERC20`, an AssetRouter boundary probe and an L1
Nullifier boundary probe.

The tested scope covers:

1. Proxy initialization and the source bridge's ERC20 deposit validation.
2. AssetRouter escrow, allowance consumption, caller/receiver/amount forwarding
   and source deposit accounting.
3. Forwarding of legacy withdrawal context to the configured L1 Nullifier.

The probe does not claim L1/L2 message inclusion proofs, Mailbox/Bridgehub
execution, zkSync batch finality or production external consensus timing. The
source-backed report row and finalized metadata are in
`dataset/reports/source_backed_harnesses.json`, while the artifact assessment is
in `dataset/reports/artifact_status.md`.

## Admission decision

This is development evidence only. It does not create mutation/trigger/control
records, independent replay evidence, owner acceptance or an evaluation corpus
seal. Evaluation readiness remains fail-closed.
