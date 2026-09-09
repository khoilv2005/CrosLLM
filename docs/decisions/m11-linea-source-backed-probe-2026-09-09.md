# Decision M11: Linea source-backed development probe

Date: 2026-09-09  
Owner: CrossLLM maintainer (single-owner development evidence)  
Lineage: `linea` / Linea rollup

## Decision

Promote the Linea harness from `generated_fixture` to
`source_backed_development_probe`. Do not treat it as evaluation admission.

## Evidence

- Source repository: `https://github.com/Consensys/linea-contracts.git`
- Locked commit: `b64fe259195f00e840d1e2a3f08b8e95e7c90918`
- Locked source archive SHA-256: `039139eb13eb7a8d554bb73b656d9cd5008095394d5039ce6e3b468044a2d6e2`
- Compiler: solc `0.8.24`, digest-pinned compiler image from the artifact lock
- Dependency closure: exact OpenZeppelin Contracts and Contracts Upgradeable 4.9.6 files
- Harness image: digest-pinned Foundry image, `network=none`, read-only source mount
- Probe result: 3/3 Foundry tests passed
- Evidence files: `dataset/harness/linea/source_manifest.json`,
  `dataset/artifacts/linea/source_receipt.json`, and
  `dataset/reports/source_backed_harnesses.json`

## Covered behavior

The probe deploys the exact `LineaRollup` source behind an isolated implementation
proxy and verifies initializer state/roles, L1 message enqueue, message identity,
rolling-hash commitment, zero-recipient rejection, and fee/value validation.

## Explicit limits

The probe does not claim blob submission, Plonk proof verification, L2 Merkle-root
anchoring, destination claim execution, external finality, or matched
mutation/control admission evidence. Those remain separate Experiment Guide gates.
