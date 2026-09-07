# CrossLLM Dataset

This package is the initial, reproducible dataset layer for CrossLLM. It is deliberately **not** a ready-made vulnerability leaderboard: no public collection can simultaneously provide real historical incidents, contamination-resistant generalization evidence, matched negative controls, and executable paired EVM artifacts.

The package contains public-source candidate metadata, host-lineage records, a strict manifest schema, and validation tooling. It does not contain exploit payloads, private mutants, private triggers, private keys, RPC credentials, or copied third-party contract code.

## Dataset layers

| Layer | Contents in this package | Scientific use |
|---|---|---|
| Historical rediscovery | `cases/historical_candidates.jsonl` | Candidate inventory only. A case becomes evaluable only after the admission gates in `docs/admission_protocol.md` pass. |
| Sealed evaluation | `cases/sealed_hosts.jsonl` and `cases/sealed_case_template.json` | Official-code host lineages and a record template. The actual mutant source and trigger must remain sealed until model evaluation is frozen. |
| Negative controls | `cases/negative_control_template.json` | Template for matched clean controls; no unverified record is counted as a negative. |
| Auxiliary traffic | `sources/source_registry.json` | RED-BRIDGE is registered only for channel/traffic calibration, never vulnerability recall. |

## Quick start

```bash
python3 tools/validate_dataset.py .
```

The command validates schema-required fields, unique identifiers, allowed roles/statuses, and cross-references to the source registry. It intentionally fails a future final release if a sealed-positive case exposes a trigger or exploit payload.

## Dataset admission rule

Do not report any record with `admission_status: candidate` as a test result. A historical candidate must be promoted to `admitted` only when it has:

1. an in-scope property family and threat profile;
2. a relevant EVM-to-EVM artifact pair, or an explicitly justified EVM-only abstraction;
3. pinned source commit, compiler settings and code/bytecode hashes;
4. independent ground-truth evidence and a safe replay validation;
5. a matched patched or benign control where obtainable;
6. lineage assignment made before any evaluation-set model tuning.

The final experiment must keep protocol lineages disjoint across development and evaluation. It must report historical rediscovery, sealed positives, and negative controls separately.

## Sources and attribution

Records point to original public sources in `sources/source_registry.json`. Third-party repositories and datasets remain governed by their own licenses and terms. Acquisition of source code, bytecode, deployment metadata, or PoCs must be recorded in the case manifest rather than copied into this package by default.

## Package status

This is a **starter dataset**. It is safe to download, validate and use to begin artifact collection. It is not yet the final paper evaluation dataset because the paired artifact/replay admission work and sealed-mutant construction have not been completed.
