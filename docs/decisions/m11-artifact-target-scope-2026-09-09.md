# M11 artifact target scope decision — 2026-09-09

## Decision

- Across uses the concrete production contract `Ethereum_SpokePool` from
  `contracts/spoke-pools/Ethereum_SpokePool.sol` at the locked Across commit.
- The Wormhole EVM SDK commit contains `WormholeRelayerReceiver` only as an
  abstract application hook. It does not contain a deployable application
  receiver. The artifact/compiler probe therefore uses the concrete SDK
  production contract `Proxy` from `src/proxy/Proxy.sol`.

## Scope and limitation

The Wormhole pack is evidence for the SDK proxy/infrastructure component. It
must not be interpreted as an evaluation of an application-level Wormhole
receiver, peer registry, or delivery handler. The abstract receiver remains
excluded; no mock or test contract is substituted.

## Evidence

- Source target classification rejects the abstract receiver before invoking
  Foundry.
- The locked Foundry probe produced deployable ABI, storage, and bytecode for
  `Proxy` and `Ethereum_SpokePool`.
- The resulting packs remain `build_probe_only` until the full source-backed
  harness, paired controls, immutable locks, and owner acceptance gates pass.
