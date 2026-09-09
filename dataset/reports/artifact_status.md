# CrossLLM Dataset Artifact Status Report (Audit Assessment)

## 1. Executive Summary

- **Total Locked Lineages**: 16 (4 Development, 12 Evaluation)
- **Source-pinned registry entries**: 4 / 16; source-pinned is not case admission.
- **Artifact packs present**: 16; 16 contain non-empty bytecode files (unverified).
- **Paired-domain harnesses**: 16 source-backed development probes and 0 generated fixtures; independent replay and evaluation admission are not proven.
- **Admission status**: NOT EXPERIMENT READY. Build probes and non-empty bytecode do not establish ancestry, mutation, trigger, control or owner-acceptance evidence.

## 2. Lineage Artifact Status Matrix

| Lineage ID | Protocol | Split | Target Contracts | Functions | Events | Storage Slots | Artifacts Hashed | Readiness Status | Bytecode Status | Provenance |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `hop` | Hop Protocol | development | `L1_Bridge`, `L2_Bridge` | 99 | 24 | 38 | 17 files | `NOT_EXPERIMENT_READY; source-backed harness` | `Non-empty (unverified)` | `lock=source_pinned; pack=source_pinned_and_built; checkout=source_pinned` |
| `layerzero_v2` | LayerZero v2 | development | `SendUln302` | 23 | 11 | 6 | 13 files | `NOT_EXPERIMENT_READY; source-backed harness` | `Non-empty (unverified)` | `lock=source_pinned; pack=source_pinned_and_built; checkout=source_pinned` |
| `celer_cbridge` | Celer cBridge | development | `CBridge` | 5 | 4 | 1 | 13 files | `NOT_EXPERIMENT_READY; source-backed harness` | `Non-empty (unverified)` | `lock=source_pinned; pack=source_pinned_and_built; checkout=source_pinned` |
| `chainbridge` | ChainBridge | development | `Bridge`, `ERC20Handler` | 51 | 11 | 14 | 17 files | `NOT_EXPERIMENT_READY; source-backed harness` | `Non-empty (unverified)` | `lock=source_pinned; pack=source_pinned_and_built; checkout=source_pinned` |
| `hyperlane` | Hyperlane | evaluation | `Mailbox` | 27 | 9 | 11 | 13 files | `NOT_EXPERIMENT_READY; source-backed harness` | `Non-empty (unverified)` | `lock=locked_commit_only; pack=source_pinned_and_built; checkout=source_pinned` |
| `axelar_gmp` | Axelar GMP | evaluation | `AxelarAmplifierGateway` | 33 | 10 | 0 | 13 files | `NOT_EXPERIMENT_READY; source-backed harness` | `Non-empty (unverified)` | `lock=locked_commit_only; pack=source_pinned_and_built; checkout=source_pinned` |
| `synapse` | Synapse Protocol | evaluation | `SynapseBridge` | 34 | 15 | 14 | 13 files | `NOT_EXPERIMENT_READY; source-backed harness` | `Non-empty (unverified)` | `lock=locked_commit_only; pack=source_pinned_and_built; checkout=source_pinned` |
| `wormhole_evm_sdk` | Wormhole | evaluation | `Proxy` | 0 | 0 | 0 | 13 files | `NOT_EXPERIMENT_READY; source-backed harness` | `Non-empty (unverified)` | `lock=locked_commit_only; pack=source_pinned_and_built; checkout=source_pinned` |
| `across` | Across Protocol | evaluation | `Ethereum_SpokePool` | 65 | 25 | 30 | 13 files | `NOT_EXPERIMENT_READY; source-backed harness` | `Non-empty (unverified)` | `lock=locked_commit_only; pack=source_pinned_and_built; checkout=source_pinned` |
| `stargate` | Stargate Finance | evaluation | `Bridge`, `Pool`, `Router` | 120 | 27 | 39 | 21 files | `NOT_EXPERIMENT_READY; source-backed harness` | `Non-empty (unverified)` | `lock=locked_commit_only; pack=source_pinned_and_built; checkout=source_pinned` |
| `arbitrum_token_bridge` | Arbitrum Token Bridge | evaluation | `L1GatewayRouter`, `L2GatewayRouter` | 37 | 9 | 11 | 17 files | `NOT_EXPERIMENT_READY; source-backed harness` | `Non-empty (unverified)` | `lock=locked_commit_only; pack=source_pinned_and_built; checkout=source_pinned` |
| `optimism` | Optimism Bedrock | evaluation | `OptimismPortal2`, `L1CrossDomainMessenger` | 63 | 13 | 43 | 17 files | `NOT_EXPERIMENT_READY; source-backed harness` | `Non-empty (unverified)` | `lock=locked_commit_only; pack=source_pinned_and_built; checkout=source_pinned` |
| `zksync_era` | zkSync Era | evaluation | `L1ERC20Bridge` | 15 | 3 | 8 | 13 files | `NOT_EXPERIMENT_READY; source-backed harness` | `Non-empty (unverified)` | `lock=locked_commit_only; pack=source_pinned_and_built; checkout=source_pinned` |
| `polygon_zkevm` | Polygon zkEVM / Agglayer | evaluation | `AgglayerBridge` | 35 | 8 | 24 | 13 files | `NOT_EXPERIMENT_READY; source-backed harness` | `Non-empty (unverified)` | `lock=locked_commit_only; pack=source_pinned_and_built; checkout=source_pinned` |
| `scroll` | Scroll | evaluation | `L1ScrollMessenger`, `L2ScrollMessenger` | 38 | 17 | 39 | 17 files | `NOT_EXPERIMENT_READY; source-backed harness` | `Non-empty (unverified)` | `lock=locked_commit_only; pack=source_pinned_and_built; checkout=source_pinned` |
| `linea` | Linea | evaluation | `LineaRollup` | 64 | 22 | 41 | 13 files | `NOT_EXPERIMENT_READY; source-backed harness` | `Non-empty (unverified)` | `lock=locked_commit_only; pack=source_pinned_and_built; checkout=source_pinned` |

## 3. Findings & Required Engineering Steps

1. **Source admission**: verify locked archive, ancestry, component licenses and clean-tree policy; record owner acceptance and Codex self-check, without claiming a second review.
2. **Build closure**: retain selected contracts, compiler/settings, ABI, bytecode, storage, dependencies, libraries, proxy/initializer and deployment configuration; non-empty bytecode alone is insufficient.
3. **Native paired harness**: deploy exact source-backed contracts in isolated EVM domains, execute normal workflow and independently validate mutations/controls.
4. **Admission**: attach private evidence hashes, matched-control validation and owner acceptance records before using the final manifest; retain the single-operator limitation.

