# CrossLLM Dataset Licensing and Legal Audit Report

## 1. Executive Summary

A comprehensive legal and licensing audit was conducted across all 16 locked lineages in the CrossLLM research dataset. Smart contract repositories utilize diverse open-source and source-available licenses:
- **Permissive Open Source**: MIT (5 lineages), Apache-2.0 (5 lineages)
- **Copyleft Open Source**: LGPL-3.0 (1 lineage), GPL-3.0 (1 lineage), AGPL-3.0 (1 lineage)
- **Source-Available / Business Source**: BUSL-1.1 (4 lineages)

This audit establishes the legal boundaries for academic benchmarking, research publication, derivative dataset distribution, and adversarial vulnerability synthesis.

---

## 2. Lineage License Classification Matrix

| Lineage ID | Protocol | Pinned License | SPDX Identifier | Category | Academic Benchmark Redistribution |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `hop` | Hop Protocol | MIT License | `MIT` | Permissive | Permitted (unrestricted) |
| `layerzero_v2` | LayerZero v2 | Business Source License 1.1 | `BUSL-1.1` | Source-Available | Permitted for non-production research |
| `celer_cbridge` | Celer cBridge | GNU General Public License v3.0 | `GPL-3.0` | Strong Copyleft | Permitted (with source attribution) |
| `chainbridge` | ChainSafe ChainBridge | GNU Lesser General Public License v3.0 | `LGPL-3.0-only` | Weak Copyleft | Permitted |
| `hyperlane` | Hyperlane | Apache License 2.0 | `Apache-2.0` | Permissive | Permitted |
| `axelar_gmp` | Axelar Amplifier Gateway | Apache License 2.0 | `Apache-2.0` | Permissive | Permitted |
| `synapse` | Synapse Bridge | MIT License | `MIT` | Permissive | Permitted |
| `wormhole_evm_sdk` | Wormhole EVM SDK | Apache License 2.0 | `Apache-2.0` | Permissive | Permitted |
| `across` | Across Protocol v2 | Business Source License 1.1 | `BUSL-1.1` | Source-Available | Permitted for research evaluation |
| `stargate` | Stargate Finance | Business Source License 1.1 | `BUSL-1.1` | Source-Available | Permitted for research evaluation |
| `arbitrum_token_bridge` | Arbitrum Token Bridge | Apache License 2.0 | `Apache-2.0` | Permissive | Permitted |
| `optimism` | Optimism Bedrock | MIT License | `MIT` | Permissive | Permitted |
| `zksync_era` | zkSync Era | MIT License | `MIT` | Permissive | Permitted |
| `polygon_zkevm` | Polygon zkEVM / Agglayer | GNU Affero GPL v3.0 | `AGPL-3.0` | Strong Network Copyleft | Permitted |
| `scroll` | Scroll Messenger | MIT License | `MIT` | Permissive | Permitted |
| `linea` | Linea Rollup | Apache License 2.0 | `Apache-2.0` | Permissive | Permitted |

---

## 3. Analysis of License Categories

### 3.1. Permissive Licenses (MIT & Apache-2.0)
- **Protocols**: Hop, Synapse, Optimism, zkSync Era, Scroll (MIT); Hyperlane, Axelar GMP, Wormhole, Arbitrum Token Bridge, Linea (Apache-2.0).
- **Permissions**: Unrestricted copying, modification, distribution, sublicensing, and analysis for both academic research and commercial applications.
- **Requirements**: Preserve copyright notices and license text in derived manifests. Apache-2.0 includes explicit patent grants and trademark limitations.

### 3.2. Copyleft Licenses (GPL-3.0, LGPL-3.0, AGPL-3.0)
- **Protocols**: Celer cBridge (GPL-3.0), ChainBridge (LGPL-3.0-only), Polygon zkEVM (AGPL-3.0).
- **Permissions**: Full reproduction, compiler analysis, bytecode extraction, and benchmark execution.
- **Dataset Boundary Compliance**: The CrossLLM dataset extracts functional interfaces (ABIs), compiler outputs (bytecode, storage layout metadata), and evaluation test fixtures without incorporating proprietary execution runtime services. The public distribution does not trigger network copyleft requirements under AGPL-3.0 because no hosted software services are operated.

### 3.3. Business Source License 1.1 (BUSL-1.1)
- **Protocols**: LayerZero v2, Across Protocol, Stargate Finance.
- **Terms**: Permits copying, modifying, and viewing the source code for non-production, evaluation, testing, and research purposes. Commercial production deployment is restricted until the change date (transitioning to GPL-2.0-or-later or Apache-2.0).
- **Academic Research Compliance**: Research benchmarking, vulnerability classification, model evaluation, and dataset analysis fall strictly within allowed non-production evaluation under BUSL-1.1 terms.

---

## 4. Public Research Boundary Compliance

In strict adherence to ethical disclosure and copyright standards:
1. **No Proprietary Secrets or Keys**: Zero private keys, mnemonic phrases, RPC URLs, or live funds are contained in the dataset.
2. **Deterministic Artifact Packaging**: The distribution package (`dist/crossllm_dataset.zip`) distributes compiled interfaces, storage representations, and deterministic test harnesses, maintaining clear provenance links back to upstream pinned git repositories.
