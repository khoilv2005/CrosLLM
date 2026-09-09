# Artifact collection protocol

`sources/source_lock.json` fixes the initial lineage partition before development tuning. It does not certify a source tree, build, bytecode, deployment or benchmark case.

## Retrieve source snapshots

```bash
python3 tools/fetch_pinned_sources.py /path/to/private-source-cache
```

The source cache is intentionally outside this public dataset package. It may contain code governed by different upstream licenses. The script checks out the exact locked commit and writes a local retrieval receipt. Do not place API keys, RPC endpoints, private artifacts or exploit material in the cache receipt.

The retrieval receipt records the resolved remote, exact `HEAD`, whether the
worktree was dirty, and the SHA-256 of `git archive --format=tar HEAD`. A dirty
worktree is retained for diagnosis but is not a clean source admission; use the
read-only audit before building.

## Per-lineage admission checklist

For each locked lineage, complete the following before adding an evaluated case:

1. identify one supported source/destination EVM path and exact contract set;
2. record `source_sha256`, source subdirectory, compiler version/settings and dependency lock;
3. compile reproducibly and record bytecode, ABI, storage-layout, linked library, proxy and initialization hashes;
4. construct a local paired EVM harness with a declared channel, finality and attestation profile;
5. execute normal workflows and a differential concrete-EVM check;
6. select a property family without using test-set LLM results;
7. create independently implemented, semantics-changing mutation(s) and a matched clean control;
8. validate the property violation and blocked trigger independently of XLIR;
9. generate a public manifest row without the exact sealed source/trigger, and an enriched private adjudication row;
10. run the dataset validator and update the status ledger.

No step may be inferred from a successful clone. A full codebase or many contracts still count as a single lineage unless evidence supports a distinct implementation ancestry.

## Generator lock

`tools/extract_all_artifacts.py` treats `sources/source_lock.json` as the
authority for repository URL, commit, and split, and uses the pinned Foundry
digest from `containers/toolchain.lock.json`. Its `--source-cache`,
`--artifacts-out`, `--harness-out` and repeated `--lineage` options make the
workflow portable; monorepos are mounted at their Git root while inspection
uses the declared Solidity subdirectory. An optional `--docker-archive-image`
must itself be digest-pinned and is used read-only with `--network=none` when a
host cannot archive a locked path. It refuses to extract when embedded
contract-selection metadata diverges from either lock. This prevents an old
generator configuration from silently rewriting an artifact pack under a new
provenance claim. Source receipts and build outputs still require review;
passing this guard is not artifact admission.

The source bind mount is read-only during `forge inspect`. Foundry's generated
cache and output are redirected to `/tmp/foundry-cache` and `/tmp/foundry-out`
through `FOUNDRY_CACHE_PATH` and `FOUNDRY_OUT` on a disposable writable tmpfs;
this is compiler scratch space, not a write path into the source checkout. The
extractor therefore supports projects whose source tree does not already have
project-local cache/output directories without weakening source immutability.

The default inspection mode is `--docker-network none`. If the pinned Foundry
image does not contain the required solc, a development operator may explicitly
use `--docker-network bridge`; the downloaded compiler and Foundry outputs stay
in disposable container scratch mounts, and the selected network is recorded
in the staging build information. This mode is still only a build probe until
the compiler version/settings and deployable contract selection are reviewed.
