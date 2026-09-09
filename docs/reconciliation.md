# Repository reconciliation

This document resolves the path names used by the Experiment Guide against the
current repository layout. It is a navigation and provenance contract; it does
not promote any proposal, artifact, source tree, or model to evaluation status.

| Guide-era reference | Current canonical location | Use | Admission boundary |
| --- | --- | --- | --- |
| `models_registry.json` | `protocol/models.json` | Declared model families, provider settings, and planned identifiers | `protocol/models.json` is planning metadata only. Runtime model identity and effective settings must come from a completed live preflight/attestation receipt. |
| `primary_sources.md` | `dataset/sources/source_lock.json`, `dataset/sources/source_registry.json`, `dataset/artifacts/lineage_reviews.jsonl` | Locked repository URL/commit, host/lineage/split mapping, and lineage review ledger | A commit lock alone is insufficient. Source retrieval, clean-tree/archive receipt, license review, ancestry review, and artifact/build evidence are required. |
| `../manuscript/tables.tex` | `paper/paper.tex` plus generated analysis tables under `analysis/outputs/` when present | Canonical paper and its result-table insertion points | Generated tables are report artifacts only after they are derived from frozen raw outcomes and their manifest/inputs are hash-addressed. |
| `manuscript/` | `paper/` | Paper source directory | `paper/paper.tex` is the sole canonical paper `.tex`; `paper/references.bib` is the bibliography. |
| benchmark manifest | `benchmark.public.jsonl` and `dataset/benchmark/benchmark.public.jsonl` | Public structural proposal/fixture | Structural validation is not admission. Use `tools/protocol_tool.py validate --mode admission` and `scripts/validate_dataset.py`. |
| private benchmark truth | `dataset/benchmark/benchmark.private.jsonl` | Restricted proposal/ground-truth payloads | Existing generated rows are not independent mutation or trigger evidence. Never publish or infer admission from their commitment hash. |

## Source of truth rules

1. `dataset/sources/source_lock.json` is authoritative for repository URL,
   locked commit, and split. The extractor's `LINEAGE_SPECS` must match those
   fields before it can write an artifact pack.
2. `containers/toolchain.lock.json` is authoritative for the pinned Foundry
   image. Floating tags are not accepted by the extractor.
3. `protocol/models.json` and `protocol/protocol.json` describe a plan until
   their runtime lock/attestation fields are completed. Live model calls use
   the Ollama Cloud API (`https://ollama.com/api/chat`) with `OLLAMA_API_KEY`;
   no local model weights are downloaded or mounted. These files must not be
   read as evidence that a model was served or that a campaign ran.
4. The public manifest may be useful for schema and pipeline rehearsal. The
   explicit `--allow-synthetic-proposal` switch in
   `scripts/generate_benchmark_manifest.py` is required because that generator
   creates deterministic fixture payloads, not independently validated cases.
5. On Windows, `scripts/audit_source_cache.py` accepts a pinned Linux image via
   `--docker-archive-image` for read-only `git archive` fallback when a locked
   commit contains a path that NTFS cannot represent. This records archive
   evidence but does not clean a worktree or promote source admission.

## Reconciliation status

The mapping is complete. The underlying evaluation prerequisites remain open:
the current source cache has dirty worktrees, some artifact receipts are stale,
the generated harnesses are not source-backed, and protocol/model admission
locks are not complete. These are tracked by the strict validator and must be
resolved with evidence rather than by changing this mapping.

The machine-readable, hash-bound copy of this mapping is
`dataset/reports/reconciliation_map.json`. Validate it independently with:

```text
python scripts/validate_reconciliation.py --check
```

The report verifies the six guide-era references, canonical path existence and
the current hashes of canonical files. It is a repository navigation artifact,
not an ancestry, reviewer, model, or benchmark-admission record.

The clean-worker installation boundary is separately exercised by
`scripts/run_clean_worker_probe.py`. Its checked-in development report is
`dataset/reports/clean_worker_probe.json`; it runs a digest-pinned Python image
with `--network=none`, a read-only root and no bind mounts. This report proves
the local development image contract only, not an evaluation worker lock.
