# M02 Development Build Spike

Date: 2026-09-09
Status: `PARTIAL`

## Current verified state (2026-09-09)

- Fresh read-only source checkouts were used for the three source-backed development lineages. Celer (`d1a097be65b3c9f0f89fabacc988de68770caa18`), ChainBridge (`b929c980afcdffae10d61c7065a5655479638519`), and LayerZero v2 (`9c741e7f9790639537b1710a203bcdfd73b0b9ac`) all report `source_pinned` with `dirty_worktree: false`.
- Celer, ChainBridge, and LayerZero source-backed harness probes pass 3/3, 5/5, and 5/5 respectively. The aggregate evidence is in `dataset/reports/source_backed_harnesses.json` and `dataset/reports/source_backed_replays.json`; all probes use the digest-pinned Foundry image, read-only source/compiler mounts, and `network_mode: none`.
- The LayerZero Windows dependency/junction issue is resolved in the extractor by mounting the dependency root and protocol package read-only and passing explicit Solidity remappings. The selected concrete target remains `SendUln302`.
- Current artifact manifest hashes are Celer `7b4beeedb4931f207250b79dfcc418ec2b5645c52ec0dbab2890ac9455ed4ecc`, ChainBridge `ab0d27edb08153a30f7d6a82b2550fdd896a3bb37ec43f03eae05f0c7a9d04d7`, and LayerZero `2e695c4de8b7e6eca07bebbe3f4bb0ef5c9d7608b15b908afc6db3633e0ad034`.
- The corresponding compiler binary hashes are Celer `addf724dcb862a48f0d0ce3407b58719dee759e5e4c4ed65023d8a060d523162`, ChainBridge `fadfc5f198e9f4eebee03db4a3d7a71534de94281f40b5d9ac72dc6b88c7cbf1`, and LayerZero `ce964c1bfb05a62099633caa7360f80ba6013b3f5529daaaa080c74654a6d577`. Dependency-closure hashes are Celer `1f60e2d369ab4fd698ba9984e23f9f9c17aa2cd53ab9bc36d3423fde0b377930`, ChainBridge `585192e44b2f6674e92a1e9253a84b0436ccbf28ecf9f3ab0d0f083f3c7ba70f`, and LayerZero `217cb2faac9a1dcf724eb6034109b67c5f5e600e61dfe39e746ababa251ccaf5`.
- This closes the current source-backed build/replay feasibility boundary for these three lineages. It remains development evidence: support matrices are owner-acceptance `draft`, evaluation admission is not enabled, and source package-lock/provenance, ancestry/license, differential ground truth, and semantic trigger adjudication remain open.

## Observations

- Hop is checked out at locked commit `0726ffa0e14745134116e552178fd7e0edcfa8e6`.
- Hop declares Node `>=11.0.0 <12.0.0` and pins `11.15.0` in `.nvmrc` and `.node-version`.
- The workstation has Node `v24.19.0`; a native build would violate the repository engine constraint.
- Historical observation: Docker CLI `29.7.2` was installed while the Docker Desktop Linux engine was not running.
- The build attempt with `node:11.15.0` could not start because the Docker API named pipe was unavailable.
- Docker is now available. `npm install` completed in `node:11.15.0`, but `npm ci` was not possible because the upstream tree has no lockfile.
- `npm run build` under Node 11 failed because the dependency range resolved a newer Hardhat using unsupported JavaScript syntax.
- A feasibility compile under Node 16 with local-only dummy URLs/accounts succeeded: 98 Solidity files compiled.
- A second Node 16 compile returned `Nothing to compile`.
- Exact direct toolchain pins were then installed: Hardhat `2.8.3`, `@nomiclabs/hardhat-ethers` `2.0.6`, `@nomiclabs/hardhat-etherscan` `2.1.5`, `@nomiclabs/hardhat-waffle` `2.0.1`, TypeScript `4.0.3`, ts-node `9.0.0`, and `@types/node` `14.11.10`.
- After deleting the private artifacts/cache, a clean Node 11.15.0 build compiled 98 files successfully using Solidity 0.5.17, 0.6.12 and 0.7.3.
- Celer cBridge compiled successfully in Node 16 with Solidity 0.8.4 and generated 9 artifacts plus 7 typechain typings.
- ChainBridge compiled successfully twice in Node 16 using a local `solc@0.8.11` compiler override; the second run reported everything up to date.
- LayerZero EVM protocol compiled with Foundry in the official Foundry container after initializing the locked `forge-std` submodule. The build produced 92 artifacts; output contained lint warnings but no compiler errors.
- A clean Foundry-container execution of the generated Hyperlane paired harness passed 3/3 tests; command/output evidence is recorded in `containers/hyperlane-foundry-probe.json`. This is only a toolchain/harness smoke probe because the contracts are generated mocks, not the source-pinned Hyperlane host.
- On 2026-09-08, `scripts/probe_foundry_harnesses.py` ran all 17 local Foundry harness projects in the pinned Foundry image with read-only mounts; 17/17 compile/test commands passed. The machine-readable output hashes are in `containers/foundry-harness-probe.json`. Solc versions were obtained by Foundry SVM at runtime because the image does not embed solc. This remains generated-harness smoke evidence, not source-pinned contract admission.
- On 2026-09-09, the source-backed extractor was probed against Hop with an
  explicit `--docker-network bridge` and disposable `/root/.svm` plus `/tmp`
  scratch while keeping the source bind read-only. ABI and storage inspection
  ran, but the locked targets `L1_Bridge` and `L2_Bridge` returned `0x` bytecode
  because both are abstract contracts. The extractor now rejects such targets
  instead of writing placeholder bytecode; this probe is recorded as rejected in
  ignored staging output and is not admission evidence.

- On 2026-09-09, the LayerZero source checkout was checked against its locked
  commit. It does not contain the previously configured `EndpointV2.sol` target;
  the concrete message-library target at that commit is
  `contracts/uln/uln302/SendUln302.sol:SendUln302`. A direct Foundry probe of that
  target compiled successfully with the locked Solidity version.
- On 2026-09-09, Docker scratch handling was changed to use `/tmp` plus
  `FOUNDRY_CACHE_PATH=/tmp/foundry-cache` and `FOUNDRY_OUT=/tmp/foundry-out`.
  Mounting child tmpfs paths under a read-only source bind is not portable when
  those directories do not already exist; the source bind remains read-only and
  the compiler cache/output remain disposable.
- The follow-up source-backed staging probe completed for LayerZero
  `SendUln302`, Celer `CBridge`, and ChainBridge `Bridge`/`ERC20Handler`.
  Deployable creation/deployed bytecode was non-empty for all selected targets;
  artifact counts were 12, 12, and 16 respectively. Staging manifest hashes are
  `b27f54c9299006581d06d85af2d212cf3f7c0ccada5f3ec0b187b2d459490e60`,
  `c8a523861e6397023db38948b0ea5c1fb5861f34e8793dc4b675991dcab12848`, and
  `9878c94c9eb70f52b566dc928eefc79e56c0aeb59ca67eb1acca53dac029adb7`.
  These are development probe outputs, not source-admission or evaluation
  artifacts.
- On 2026-09-09, the three successful source-backed probe outputs were rebuilt
  into the canonical `dataset/artifacts/` directories with `--force`. The
  rebuild clears extractor-owned ABI/bytecode/storage-layout outputs first, so
  the LayerZero pack now contains only `SendUln302` rather than the stale
  `EndpointV2` selection. The resulting packs contain 13, 17 and 13 hashed
  files respectively after deterministic per-lineage manifest regeneration.
  The source-backed harness attestation in
  `dataset/reports/source_backed_harnesses.json` records read-only,
  `--network=none` probes using the locked Solidity compiler images. Celer,
  ChainBridge and LayerZero now have `artifact_admission_status:
  source_pinned_and_built` and `source_backed: true`; this is development
  evidence only and does not bypass ancestry or evaluation admission review.

## Feasibility hashes

These hashes describe the current private probe, not an evaluation lock:

| Input/output | SHA-256 |
|---|---|
| Git archive of locked source | `1c5964ee826e1823bf7bad5f7ffb3074d802b97412194ff9ee78114331b2a702` |
| `hardhat.config.ts` | `9972001657021ac74dfc6925c83d50bd3aba61bf65b3567cfb06a87f6018e8c2` |
| Generated `package-lock.json` | `c146e6c816551528c6fa37c2535aed3fe2c1c59ff6359a85f21f52b02629809e` |
| `package.json` | `ea3b6cfc0eddd7dd766bdba86bba9940ea54ccc558a9e523e5edcd02991cab89` |
| Artifact manifest (237 files, clean Node 11 build) | `73e33ae3b3859d508dd5c334e236b5fad87f567acae5f5a798ff12ce34338432` |
| Celer artifact manifest (9 files) | `65e556ec4a1bff1e357a92497bb503f61b1524e88c21f0df4e09289f9408ff14` |
| Celer `hardhat.config.ts` | `0afd9a61654f649d7f49e7ff1c496ac9988fcf652195e1d65844b4f18890c83c` |
| Celer generated `package-lock.json` | `745d9f911cc98c20dd0167b4fb1a782fec6f8f9aa760384aeeca00040a62818f` |
| ChainBridge artifact manifest (66 files) | `908fac5b18bfdaedd4e0b81eba94d0534c3d3a0167a756d38db0c17cb2204339` |
| ChainBridge `truffle-config.js` | `cb5fdf55ea3488f76dcb75d32363eb94333345701ade2455c9bb084d1c505180` |
| ChainBridge `package-lock.json` | `2431b6d762c614ac6bf1208db574699bd7ff205e0fa485bd2623a653f093a315` |
| LayerZero artifact manifest (92 files) | `42f90db54a3364f6c6cfd8369b199726acecddf85851c60a326460d0254d3a0d` |
| LayerZero `foundry.toml` | `0fe8766f41303bfbb6c923aa741338af143ed5c8003e2903e69a8afc98d472b4` |
| LayerZero `forge-std` submodule | `2f112697506eab12d433a65fdc31a639548fe365` |

## Consequence

M02.03 remains partial for admission purposes. Hop, Celer, ChainBridge and the LayerZero EVM protocol component have compile evidence; Celer, ChainBridge and LayerZero additionally have passing source-backed paired harness probes. Full bytecode/proxy/initialization/dependency provenance, ancestry/license review, Hop deviation adjudication and selected supported contract sets are still not packaged/admitted for all development hosts.

The artifact extractor now refuses stale embedded repository/commit/split
metadata, requires the digest-pinned Foundry image, validates an existing pack's
source receipt before skipping it, rejects empty/malformed bytecode, and computes
the source archive digest from the locked cache checkout. Its Docker inspection
path is argv-based with a read-only source mount, disposable compiler scratch,
and a secure no-network default; `--docker-network bridge` is an explicit
development-only solc download probe and is recorded in build info. These
controls prevent a build probe from silently becoming an admission claim; they
do not resolve the outstanding source, license, ancestry, harness, or
independent-validation reviews.

- Historical staging record: on 2026-09-09, `containers/solc.lock.json` was added for all 13 Solidity
  versions used by the lineage specifications. The extractor now pulls the
  digest-pinned compiler image before the probe, verifies its reported version
  and binary SHA-256, copies it into a lineage-scoped disposable volume, and
  invokes Foundry with `--use /compiler/solc` and `--pull=never`. LayerZero
  `SendUln302`, Celer `CBridge`, and ChainBridge `Bridge`/`ERC20Handler` were
  each rebuilt in staging with `docker_network=none`; this removes SVM/TLS
  download from the inspect path. The staging outputs remain development-only;
  the canonical rebuilt Celer, ChainBridge, and LayerZero receipts now report
  clean pinned source and `source_pinned_and_built`.

- On 2026-09-09, the extractor added a source-level declaration gate and
  provenance check. It records the selected declaration kind and line before
  running Forge, and rejects abstract/interface/library targets fail-fast.
  The locked Hop targets are recorded in
  `dataset/reports/hop_target_review.json`; the concrete `Mock_*` test targets
  are explicitly excluded from production admission.

- On 2026-09-09, the development mutation smoke boundary was hardened. The
  ten registered operators across six property families now run with the
  digest-pinned Foundry image, locked `solc 0.8.36` copied into a disposable
  compiler volume, `--network=none`, read-only harness source and control-pair
  assertions. `dataset/benchmark/mutation_validation_spec.json` maps every
  operator to its mutant/control contracts and test trigger; the receipt
  records operator/spec/source hashes, compiler identity, explicit empty
  exclusion log and `admission_eligible: false` at
  `dataset/benchmark/trigger_validation_evidence.jsonl`; the probe passed
  10/10. This is generated development evidence only: it does not validate a
  mutation against a locked production checkout or establish independent gold
  property/trigger evidence.

- On 2026-09-09, a source-backed development mutation boundary was added for the
  locked Celer `CBridge` source at commit
  `d1a097be65b3c9f0f89fabacc988de68770caa18`. Two exact source patches were
  exercised against clean controls: replay identity-guard removal and refund
  timelock-guard removal. Both control/mutant pairs passed (`2/2`) in a
  digest-pinned Foundry container with locked `solc 0.8.9`, read-only source and
  compiler mounts, and `--network=none`. The immutable receipt is
  `dataset/reports/source_mutation_evidence.jsonl`; it records all source,
  patch, test-output and compiler hashes, but explicitly sets independent
  property/trigger validation and `admission_eligible` to false. This closes a
  development execution boundary only; it does not admit any benchmark case.

- On 2026-09-09, `verify_artifact_provenance.py` began recomputing stable
  ABI/storage symbol records from the recorded ABI, storage layout and
  explicit contract-domain map. The three source-backed development packs
  pass this recomputation and a forged stable-symbol test is rejected. This
  strengthens the M02.04 integrity boundary without changing admission status.
