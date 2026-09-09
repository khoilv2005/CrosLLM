# Decision M11: Polygon zkEVM source-backed development probe

Date: 2026-09-09  
Owner: CrossLLM maintainer (single-owner development evidence)  
Lineage: `polygon_zkevm` / Polygon zkEVM Agglayer

## Decision

Promote the Polygon zkEVM harness from `generated_fixture` to
`source_backed_development_probe`. Do not treat it as evaluation admission.

## Evidence

- Source repository: `https://github.com/0xPolygonHermez/zkevm-contracts.git`
- Locked commit: `110bda5a03e70ee7331bc06407a8e79226d3e520`
- Locked source archive SHA-256: `c4793b6fc2016ddb2ede4ec205ea264367ce711ba8e1b99304ae8edc514e6848`
- Compiler: solc `0.8.28`, digest-pinned compiler image from the artifact lock
- Harness image: digest-pinned Foundry image, `network=none`, read-only source mount
- Probe result: 3/3 Foundry tests passed
- Evidence files: `dataset/harness/polygon_zkevm/source_manifest.json`,
  `dataset/artifacts/polygon_zkevm/source_receipt.json`, and
  `dataset/reports/source_backed_harnesses.json`

## Covered behavior

The probe deploys the exact `AgglayerBridge` source behind an isolated
EIP-1967 storage proxy and verifies proxy-admin owner lookup, ERC20 approval and
escrow, canonical deposit count/Merkle-root change, same-network destination
rejection, and nonzero `msg.value` rejection for ERC20 deposits.

## Explicit limits

The probe does not claim Agglayer global-exit-root submission, rollup validity,
SMT claim proofs, destination claim execution, external finality, or matched
mutation/control admission evidence. Those remain separate Experiment Guide
gates.

## Reproducibility note

The pinned source tree contains a valid upstream path with `:` in its filename,
which Windows Git cannot archive. The source-backed helper therefore falls back
to the digest-pinned Foundry Linux image for `git archive`; the resulting hash
matches the locked receipt exactly.
