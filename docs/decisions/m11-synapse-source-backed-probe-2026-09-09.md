# M11 Synapse source-backed development probe

Date: 2026-09-09  
Lineage: `synapse`  
Scope: development evidence only; not evaluation admission

## Result

The pinned Synapse `SynapseBridge` source was materialized into the development
harness and passed a read-only, `network=none` Foundry probe with the locked
Solidity compiler. The three test cases cover source escrow, node-group role
authorization, net mint/fee accounting, kappa execution recording and replay
rejection.

The existing generated fixture was removed from the Synapse harness so the
normal-workflow runner now executes the source-backed test contract. This does
not turn the selected bridge contract into a complete production cross-chain
consensus or application-receiver model.

## Pinned evidence

- Source repository: `https://github.com/synapsecns/synapse-contracts.git`
- Source commit: `60f1c25cf2f115911e11255f515e1450fe96100c`
- Source archive SHA-256: `cab2a5e5d140dae2eefe0d26567b6595350bd668914da782e7d82ff68fab77be`
- Selected source hash: `99d1cee3c21379228a8e3cc80a304296b2aca08e0bc9a1ddbb6eb1d65cb20f72`
- Compiler: Solidity `0.6.12`
- Compiler binary SHA-256: `fab8f0275c8e6111294431eb7ddc03c12625a62b26e38f36a5ece659370f977b`
- Harness source manifest SHA-256: `e9c457d690b3e1fb2ab473394a3a726e9092fae38b2066b3b9338bd7a33e3295`
- Artifact manifest SHA-256: `8ab7d5cc01fd9bbf44c7fc3fe7a21531668850304c9f0cc3b86d9d6f2c2b58a7`
- Probe row SHA-256: `bdb7d17eef972e51773e9bb1359c4f1c99ddf51c9c8b798ff8c3e37405d6ca51`
- Test source SHA-256: `1989542aa124a6e9b068c5ca4ea02b5244a9b173a8f1839e07871796fe42276f`

## Verification

```text
source_backed_harnesses.py --lineage synapse --finalize: PASS, 3/3
validate_normal_workflow.py --check: PASS, 16/16 lineages
python -m unittest discover -s tests -p "test_*.py": PASS, 421 tests
python -m unittest discover -s tools -p "test_*.py": PASS, 19 tests
dataset/tools/validate_dataset.py dataset: PASS
scripts/validate_dataset.py: LOCAL_INTEGRITY PASS; EVALUATION_READINESS BLOCKED
```

The development result remains non-admission because mutation/trigger/control
evidence, independent replay/adjudication, runtime model attestation, owner
acceptance and the complete sealed evaluation corpus are still absent.
