# Development container evidence

`toolchain.lock.json` records image digests observed on 2026-09-08. These are
development probes, not evaluation locks. The repository uses separate Node
images for legacy source builds and a Foundry image for Solidity probes because
the source lineages require incompatible Node/compiler combinations.

Example read-only version probes:

```powershell
docker run --rm ghcr.io/foundry-rs/foundry@sha256:0c00cb0bda1ab1b91c9a6bf60f4c76c09c1a8870824b6d4718afbabacf6f9a17 'forge -V'
docker run --rm node@sha256:67ca28addce8ae818b144114a9376a6603aba09069b7313618d37b38584abba1 node --version
```

The Foundry image currently reports forge 1.8.1 and does not include `solc`.
The Python runtime boundary is `requirements.lock`; it is SHA-256 wheel-hashed
and CI installs it with `pip --require-hashes` on `ubuntu-24.04`. The lock has
explicit Z3 platform variants because the observed Windows wheel
(`5.1.0.0`) is not the Linux CI artifact (`4.15.4.0`).

`solc` is locked separately in `solc.lock.json`: every Solidity version
declared by the lineage specifications resolves to a digest-pinned
`ghcr.io/argotorg/solc` image. The extractor copies and verifies that compiler
into a lineage-scoped disposable volume, then invokes Foundry with
`--use /compiler/solc` and `--network=none`. The compiler image is pulled as a
separate setup step and extraction containers use `--pull=never`, so an inspect
probe cannot silently wait on a registry or SVM download.

These are still development toolchain inputs, not evaluation locks. Before
M00.01/M00.03 are accepted, capture clean-run outputs, complete dependency and
worker-image locks, and select the worker image after the backend feasibility
decision. No private gold or evaluation source should be mounted into these
probes.
