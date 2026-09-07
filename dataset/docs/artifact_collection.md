# Artifact collection protocol

`sources/source_lock.json` fixes the initial lineage partition before development tuning. It does not certify a source tree, build, bytecode, deployment or benchmark case.

## Retrieve source snapshots

```bash
python3 tools/fetch_pinned_sources.py /path/to/private-source-cache
```

The source cache is intentionally outside this public dataset package. It may contain code governed by different upstream licenses. The script checks out the exact locked commit and writes a local retrieval receipt. Do not place API keys, RPC endpoints, private artifacts or exploit material in the cache receipt.

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
