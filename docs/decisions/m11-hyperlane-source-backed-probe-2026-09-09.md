# Hyperlane source-backed development probe — 2026-09-09

The Hyperlane development harness was upgraded from a generated protocol
fixture to a source-backed development probe. Its `Mailbox.sol` and local
library/interface closure are copied byte-for-byte from the locked
`8ae786a778857216ad31325f741e9f9cb01b3088` checkout. The harness uses the
locked Solidity `0.8.33` compiler image, a digest-pinned Foundry image, and
read-only source/compiler mounts with `network=none`.

The probe passed two tests: a normal dispatch/process lifecycle with recipient
callback and delivery identity, and rejection when the interchain security
module denies the message. The result is recorded in
`dataset/reports/source_backed_harnesses.json` and finalized in the Hyperlane
artifact/harness metadata.

This is still development evidence. The harness uses deterministic test
doubles for the ISM and post-dispatch hooks, and does not establish any
evaluation mutation, trigger, control, independent property evaluator,
owner-accepted corpus admission, or runtime lock. It must not be counted as a
sealed benchmark result.
