# Evaluation admission validation

The protocol validator has two intentionally different evaluation paths:

- `--mode evaluation` checks the public manifest's structural shape. It may
  pass for a proposed/sealed fixture and explicitly reports that semantic
  ground truth, ancestry, identity and implementation correctness are not
  checked.
- `--mode admission` additionally requires an admitted status, source archive,
  artifact/deployment/harness hashes, trigger evidence, mutation or negative
  control evidence, and an `admission_acceptance` record containing the project
  owner decision plus the Codex self-check. This workspace does not require a
  second reviewer; the deviation is recorded in
  `docs/decisions/m00-review-policy-2026-09-09.md`. It uses
  `schemas/benchmark_admission.schema.json` by default and fails closed.
- `--mode final` applies the same admission checks and additionally requires
  the registered 240-row design: 120 sealed positives, 120 matched controls,
  twelve lineages, ten positives/controls per lineage, twenty rows per
  property family in each cohort, reciprocal pairs, and distinct positive /
  control artifact packs. It is the final-manifest gate; it does not infer
  missing evidence from commitment hashes.

Example:

```bash
python tools/protocol_tool.py validate \
  --manifest benchmark.public.jsonl \
  --mode admission
```

For a completed evaluation manifest, use the stricter design gate:

```bash
python tools/protocol_tool.py validate \
  --manifest benchmark.public.jsonl \
  --mode final
```

The current public manifest is expected to fail this command. Structural
validity and a commitment receipt are not substitutes for case admission.
