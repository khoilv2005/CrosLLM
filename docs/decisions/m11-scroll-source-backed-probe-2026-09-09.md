# M11 Scroll source-backed probe

Date: 2026-09-09  
Status: `SOURCE_BACKED_DEVELOPMENT_PROBE_PASS`; not evaluation admission.

## Locked inputs

- Repository: `https://github.com/scroll-tech/scroll-contracts.git`
- Commit: `dfbd661520ac30505a773881728cc5cfb005978b`
- Selected targets: `src/L1/L1ScrollMessenger.sol` and
  `src/L2/L2ScrollMessenger.sol`
- Compiler: `solc 0.8.24`, digest-pinned compiler image
- Foundry: digest-pinned image
- Probe network: `none`
- Harness mount: read-only source and compiler inputs

## Evidence

`ScrollSourceBackedHarnessTest` passed 4/4 tests. The harness uses the exact
locked source closure for both source messengers, their selected libraries,
interfaces and source `L2MessageQueue` closure, plus the exact OpenZeppelin
upgradeable v4.9.3 files required by `ScrollMessengerBase`. Generated support
is limited to queue and receiver boundary probes.

The tested scope covers:

1. L1 message enqueue and source-generated relay calldata.
2. L2 message enqueue and source-generated message hash.
3. L2 relay through the source alias-authority check and receiver callback.
4. Successful relay terminal state and replay rejection, including wrong
   authority rejection.

The probe does not claim ScrollChain batch finality, withdrawal Merkle proof
verification, production queue deployment or external cross-chain timing. The
source-backed report row and finalized metadata are in
`dataset/reports/source_backed_harnesses.json`, while the artifact assessment is
in `dataset/reports/artifact_status.md`.

## Admission decision

This is development evidence only. It does not create mutation/trigger/control
records, independent replay evidence, owner acceptance or an evaluation corpus
seal. Evaluation readiness remains fail-closed.
