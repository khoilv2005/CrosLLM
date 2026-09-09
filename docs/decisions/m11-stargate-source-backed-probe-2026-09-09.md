# M11 Stargate source-backed development probe

Date: 2026-09-09  
Lineage: `stargate`  
Scope: development evidence only; not evaluation admission

## Result

The pinned Stargate `Bridge`, `Pool`, `LPTokenERC20`, `Factory` and `Router`
sources were materialized into the harness and the native credit-delivery path
passed in a read-only, `network=none` Foundry probe with Solidity `0.7.6`.
The normal test deposits liquidity, creates and distributes pool credits,
executes the source `Bridge.sendCredits`, delivers through an endpoint test
double, and executes the destination source `Bridge.lzReceive` into the
destination source `Pool`.

The harness uses a small router-controller test double because the source
deployment path requires a circular Router/Bridge/Factory setup. The controller
is only infrastructure; all asserted bridge/pool state transitions are from
the locked source contracts. The selected scope does not claim swap pricing,
external LayerZero finality, or a complete production deployment.

## Pinned evidence

- Source repository: `https://github.com/stargate-protocol/stargate.git`
- Source commit: `c4212c2ee76997b1099ee9b34da0f1ed32dcf9c4`
- Source archive SHA-256: `876da7f357274f3e55a182fd7f8433c151a1196037022fb2f745f2d45a1ddcf2`
- Selected source hash: `3a2eb754f88b6238f3f6a3896678607cbd6967a6eb8eb42c796fe519cb5981bd`
- Compiler: Solidity `0.7.6`
- Compiler binary SHA-256: `19499cc8e2b83f4aa794c872f0b1523f38e121144f8bb853ef8618417e0a6bf2`
- Harness source manifest SHA-256: `021d89e6393e5466cf983d7ad123ab5b86888078e7ed4af36083984da6c2f9ec`
- Artifact manifest SHA-256: `f331f26beab8ba5bc79efecc2cae20948d696ece43a8e5d60605253a2a902dae`
- Probe row SHA-256: `94b2b7eb54030f03b9aa09112205da5c929b459c03cf6e2d88aa8a7994104b82`
- Test source SHA-256: `a549d2febdf040f9ce57f7d3a43b7afca7a61efa139c9809a5bb8c76a6e65368`

## Verification

```text
source_backed_harnesses.py --lineage stargate --finalize: PASS, 3/3
normal_workflow_test.py: PASS
validate_normal_workflow.py --check: PASS, 16/16 lineages (latest full run)
python -m unittest discover -s tests -p "test_*.py": PASS, 421 tests
python -m unittest discover -s tools -p "test_*.py": PASS, 19 tests
dataset/tools/validate_dataset.py dataset: PASS
scripts/validate_dataset.py: LOCAL_INTEGRITY PASS; EVALUATION_READINESS BLOCKED
```

This remains non-admission evidence. Mutation/trigger/control validation,
independent replay/adjudication, runtime model attestation, owner acceptance
and the complete sealed evaluation corpus are still required.
