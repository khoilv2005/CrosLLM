# Wormhole SDK proxy source-backed development probe — 2026-09-09

The Wormhole artifact scope is the concrete `src/proxy/Proxy.sol` contract
from locked commit `2cb855ea9d0a6c28470620a6d37c04d0496ea919`, together with its
exact `Eip1967Implementation.sol` dependency. A source-backed development
probe now exercises proxy construction, the `checkedUpgrade` initialization
boundary, fallback delegation, and delegated storage updates. It passed two
tests under the locked Solidity `0.8.30` compiler, digest-pinned Foundry, and
read-only source/compiler mounts with `network=none`.

The probe is intentionally limited to the selected SDK proxy scope. The
locked SDK target does not provide a concrete application receiver or a full
Wormhole CoreBridge deployment in this artifact closure. Therefore this result
does not establish Wormhole message verification, guardian quorum behavior,
mutations, controls, independent property evaluation, or evaluation admission.
