# Analysis and inference boundary

`src/crossllm/analysis/estimands.py` consumes frozen raw campaign outcomes and
implements the protocol hierarchy: campaign replicates are averaged within
instances, instances within lineage, and lineages receive equal weight. Paired
method differences are formed on matched instances before lineage aggregation.
Negative-control false-alert rate, false-discovery proportion, useful-proposal
recall, native-witness yield, independent-replay rate and restricted witness/
claim time are separate endpoints with explicit stage denominators.

`None` measurements remain missing. Time endpoints use the declared horizon as a
right-censoring score, while the report still exposes how many underlying times
were missing. Precision is `null`/N.A. when no claims are emitted.

`analysis/inference.py` and `analysis/reporting.py` provide seeded paired-lineage
bootstrap summaries (default 10,000 draws), exact two-sided sign tests with ties
and effective `n`, Holm correction within a supplied family, zero-event bounds,
and leave-one-lineage-out sensitivity. `agreement_summary` can additionally
bootstrap complete lineage clusters for categorical-label confidence intervals;
it does not treat correlated findings as independent. Primary and secondary
contrast families are passed separately so multiplicity is not silently pooled.

The current implementation is a tested analysis core, not a result report: no
real evaluation raw data, admitted ground truth, or numerical paper results have
been inserted.

`AnalysisArtifactBuilder` and `crossllm analysis-build` provide a strict
JSONL-to-JSON boundary. Raw rows are canonicalized for an input hash, optional
measurements remain null/missing, and primary/secondary contrast families are
analyzed separately with seeded bootstrap/sign-test settings. This remains a
development artifact until its input is a frozen, adjudicated evaluation raw
export.

Each method also carries separate witness/claim time details: restricted time
score (`min(T, tau)` with no-event/failure censored at `tau`),
availability-conditioned score, intention-to-run fraction and a descriptive
Kaplan--Meier survival table. These values retain their availability and
missingness denominators.

`build_analysis_tables` produces eleven deterministic table artifacts (eight
endpoint tables, stage denominators, a separate conditioned-time table and
inference). Each table can be emitted
as CSV with `AnalysisTable.write_csv`; table rows are included in the analysis
artifact hash so a paper table cannot silently come from different raw input.
`AnalysisArtifact.write_bundle` emits the JSON artifact, all eleven CSVs and a
hash-linked `manifest.json` in one directory; the CLI accepts `--bundle-out` for
this export. The bundle contains no manuscript fragment.

For an evaluation-shaped analysis invocation, supply separate JSON maps with
`--primary-contrasts` and `--secondary-contrasts` and add
`--require-prespecified-families`. Strict mode requires exactly five primary
contrasts and six secondary contrasts, applies Holm correction within each
family only, and rejects non-finite lineage effects. Omitting these files
remains valid for development artifacts but produces no inferential contrasts.

The verification-stage bridge is `scripts/build_paired_verification_analysis.py`.
It loads one shared `verification_campaign` JSONL, projects the same campaigns
at `Recall@1/@2/@4/@8`, and emits verification metrics plus method analysis rows
without changing stage missingness. Repeat `--compare LEFT RIGHT` for paired
method contrasts, for example:

```text
python scripts/build_paired_verification_analysis.py \
  --input results/verification_campaigns.jsonl \
  --out results/paired-analysis.json \
  --bundle-out results/paired-analysis-bundle \
  --compare crossllm direct \
  --compare crossllm t0 \
  --expected-input-hash FROZEN_SHA256
```

`--expected-input-hash` aborts on a changed campaign input. The optional
per-prefix bundle contains the analysis JSON, eleven CSV tables and a manifest
hash. This command is an analysis boundary only: it cannot promote proposal
archives or unavailable verification stages into verified findings.
If one input contains multiple model tags, pass `--model-tag`; otherwise the
command aborts instead of mixing model-specific paired units.

When the verification runner has archived timing data, the report also
contains `resource_metrics`: provider input/output tokens, transport time,
Ollama-reported duration, shared verification-stage time and caller-supplied
wall time. These are separate from Recall/FDP and have their own known,
missing and not-applicable denominators; no dollar cost or reasoning-token
breakdown is inferred from Ollama responses.

`analysis/figures.py` provides the complementary figure boundary. It emits
paired-lineage, recall@N, time-curve, scaling and failure-flow SVGs only from
explicit supplied series. Every figure records a canonical `source_hash` and
`svg_hash`; missing series produce no placeholder chart. The CLI command is:

```text
crossllm analysis-figures --spec FIGURE_SPEC.json --out results/figures
```

The generated `figures.json` is a manifest, while each SVG remains traceable
to the frozen numeric input. It is not a substitute for an analysis run and
does not infer estimates from synthetic or missing rows.

`scripts/run_analysis_rehearsal.py` exercises the complete M09 boundary on
synthetic rows: blinded labels/reconciliation, the 11-class first-failure
taxonomy, stratified rejection sampling, 10,000-draw paired inference, all
eleven CSV tables and the five prespecified SVG figure types. Its report is
`dataset/reports/m09_analysis_rehearsal.json`; it records zero provider calls
and is explicitly non-admission.

The canonical manuscript has one marked generated region between
`BEGIN/END GENERATED:tab:main-v2`. `scripts/update_paper_tables.py` can update
that region from a frozen analysis artifact while preserving `\\ResultTBD` for
missing confidence intervals or time metrics. No second manuscript `.tex`
fragment is created.
