# M07 sensitivity matrix and recall endpoints

`build_sensitivity_matrix` in `src/crossllm/baselines/sensitivity.py` is the
single code path for the prespecified M07.07 Cartesian product. The default
dimensions are:

- proposal prefixes `1/2/4/8`;
- `k_tx = 2/4/6/8`;
- `(k_ch, B) = (6,1)/(12,2)/(24,4)`;
- solver limits `10/30/120` seconds and horizons `15/60` minutes;
- FIFO/reordering, no-reorg/bounded-pre-finality reorg, and challenge
  before/at/after;
- caller-supplied attestation profiles and program-size strata.

The builder does not infer support from success. Without an eligibility resolver
cells are `pending`; a resolver must return an explicit denominator for an
eligible cell or a reason for an unsupported cell. The matrix hash covers all
dimensions, budgets and eligibility decisions.

For a development-only pending matrix, use for example:

```bash
PYTHONPATH=src python scripts/generate_sensitivity_matrix.py \
  --output build/m07-sensitivity.pending.json \
  --method X --method P --track automatic \
  --attestation-profile honest --program-size-stratum small
```

The output is deliberately `pending` until an eligibility resolver supplies
per-cell denominators or unsupported reasons. It is not an evaluation lock.

## Two recall endpoints

`proposal_prefix_recall` consumes only an archived ordered property-ID batch.
It reports whether each instance has a gold property in the first `N` entries.
`end_to_end_budget_recall` consumes scheduled campaign observations keyed by
budget `N`. The two result types and endpoint labels are distinct by design;
end-to-end outcomes must not be substituted for proposal-prefix recall.

Both endpoints retain missing archives/outcomes in `total` and expose them as
`missing`, without silently converting them to zero. A missing or unsupported
cell is retained in operational reporting and must carry a reason before it is
used for an evaluation claim.
