# CrossLLM Dataset Reproducibility Report

## 1. Overview and Environment Requirements

This report details the exact, deterministic build instructions, container configurations, dependency isolation steps, and cryptographic checksum procedures required to independently reproduce every compiler artifact, ABI, storage layout, bytecode, and paired harness metadata across all 16 CrossLLM protocol lineages.

### System & Container Environment
- **Operating System**: Linux container runtime (Docker on Ubuntu 22.04 LTS / x86_64 or WSL2 / Windows Docker Engine)
- **Primary Toolchain Container**: `ghcr.io/foundry-rs/foundry@sha256:0c00cb0bda1ab1b91c9a6bf60f4c76c09c1a8870824b6d4718afbabacf6f9a17` (Forge `1.8.1` observed; the image does not embed solc binaries)
- **Dependency Toolchain Containers**:
  - `node@sha256:c6ae79e38498325db67193d391e6ec1d224d96c693a8a4d943498556716d3783` (Node `18.20.8`, reserved compatibility probe)
  - `node@sha256:f77a1aef2da8d83e45ec990f45df50f1a286c5fe8bbfb8c6e4246c6389705c0b` (Node `16`, Celer/ChainBridge development probe)
- **Hash Specification**: GNU / POSIX `tar` archive checksum computed via:
  ```bash
  git archive --format=tar HEAD | sha256sum
  ```
  *(Computed inside Linux container to eliminate Windows CR/LF and permission mode variance).*

---

## 2. Lineage Build Specifications & Mount Layouts

To reproduce artifact extraction without missing dependencies, monorepo repositories must mount their repository root while setting the container working directory to the Solidity package directory:

| Lineage ID | Repository Root Mount | Container Workdir (`-w`) | Solc Version | Compiler Optimizations |
| :--- | :--- | :--- | :--- | :--- |
| `hop` | `/hop` | `/src` | 0.6.12 | 50,000 runs |
| `layerzero_v2` | `/layerzero_v2` | `/src/packages/layerzero-v2/evm/messagelib` | 0.8.36 | Default (Foundry) |
| `celer_cbridge` | `/celer_cbridge` | `/src` | 0.8.9 | 800 runs |
| `chainbridge` | `/chainbridge` | `/src` | 0.8.11 | 200 runs |
| `hyperlane` | `/hyperlane` | `/src/solidity` | 0.8.33 | Default (Foundry) |
| `axelar_gmp` | `/axelar_gmp` | `/src` | 0.8.36 | Default (Foundry) |
| `synapse` | `/synapse` | `/src` | 0.6.12 | Default |
| `wormhole_evm_sdk` | `/wormhole_evm_sdk` | `/src` | 0.8.30 | Default (Foundry) |
| `across` | `/across` | `/src` | 0.8.30 | 10,000 runs |
| `stargate` | `/stargate` | `/src` | 0.7.6 | Default (Foundry) |
| `arbitrum_token_bridge` | `/arbitrum_token_bridge` | `/src` | 0.8.16 | Default (Foundry) |
| `optimism` | `/optimism` | `/src/packages/contracts-bedrock` | 0.8.15 | Default (Foundry) |
| `zksync_era` | `/zksync_era` | `/src/l1-contracts` | 0.8.28 | 9,999,999 runs |
| `polygon_zkevm` | `/polygon_zkevm` | `/src` | 0.8.20 | Default (Foundry) |
| `scroll` | `/scroll` | `/src` | 0.8.24 | 200 runs |
| `linea` | `/linea` | `/src` | 0.8.19 | Default (Foundry) |

---

## 3. Step-by-Step Reproduction Workflow

### Step 1: Repository Acquisition and Commit Pinning
For each lineage, clone the upstream repository and check out the exact locked commit:
```bash
git clone <source_repo> <lineage_dir>
cd <lineage_dir>
git checkout <pinned_commit>
```

### Step 2: Canonical Archive Hash Verification
Compute the POSIX tar archive SHA-256 hash using the Linux container:
```bash
docker run --rm --network=none --read-only \
  -v <private-source-cache>:/sources:ro \
  --entrypoint git \
  node@sha256:f77a1aef2da8d83e45ec990f45df50f1a286c5fe8bbfb8c6e4246c6389705c0b \
  -C /sources/<lineage> archive --format=tar HEAD > source.tar
sha256sum source.tar
```
The read-only source audit uses the pinned Node 16 image above as an
archive-only fallback when the host cannot represent a locked path. Verify
that the archive hash strictly matches the expected source receipt before
using it as build evidence. The Foundry image remains the compiler/inspection
image in Step 3.

### Step 3: Foundry / Solc Compilation & Inspection
Execute `forge inspect` to extract the ABI, creation bytecode, deployed bytecode, and storage layout:
```bash
# ABI Extraction
docker run --rm --network=none --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges -v <repo_mount>:/src:ro -w <workdir> \
  --entrypoint forge \
  ghcr.io/foundry-rs/foundry@sha256:0c00cb0bda1ab1b91c9a6bf60f4c76c09c1a8870824b6d4718afbabacf6f9a17 \
  inspect <ContractName> abi --json

# Deployed Bytecode Extraction
docker run --rm --network=none --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges -v <repo_mount>:/src:ro -w <workdir> \
  --entrypoint forge \
  ghcr.io/foundry-rs/foundry@sha256:0c00cb0bda1ab1b91c9a6bf60f4c76c09c1a8870824b6d4718afbabacf6f9a17 \
  inspect <ContractName> deployedBytecode

# Storage Layout Extraction
docker run --rm --network=none --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges -v <repo_mount>:/src:ro -w <workdir> \
  --entrypoint forge \
  ghcr.io/foundry-rs/foundry@sha256:0c00cb0bda1ab1b91c9a6bf60f4c76c09c1a8870824b6d4718afbabacf6f9a17 \
  inspect <ContractName> storage --json
```

### Step 4: Verification of Dataset Integrity & Workflows
Run the automated test suite from the repository root:
```bash
# 1. Local artifact integrity and evaluation readiness
python dataset/tools/validate_dataset.py dataset
# The command returns exit code 2 until source-backed admission, locks and
# independent evidence are present. A zero exit code is required for evaluation.

# 2. Paired cross-domain normal workflow test suite
python scripts/validate_normal_workflow.py

# 3. Master checksum verification
python scripts/hash_artifacts.py
```

---

## 4. Deterministic Checksum Verification
The generated artifact/harness snapshot has SHA-256 digests recorded in
`dataset/checksums.sha256`. This verifies local file integrity only; it does
not establish source ancestry, deployment provenance, semantic ground truth or
evaluation admission. Independent replicators can verify the snapshot with:
```bash
cd dataset && sha256sum -c checksums.sha256
```
