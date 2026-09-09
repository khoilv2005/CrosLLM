# Blinded adjudication boundary

`src/crossllm/adjudication/ledger.py` implements the development contract for
M09.01–M09.03:

- `BlindedFinding` is exported without method/backbone identity;
- two rater labels are immutable and cannot be overwritten by the same rater;
- a third, independent adjudicator creates a reconciliation, preserving both
  pre-consensus labels, rater roles, explicit `role_overlap`, and disagreements
  as `unresolved`;
- relabeling is append-only history, not an in-place rewrite;
- proposal-to-requirement mapping is a separate record and is not inferred from
  downstream replay success;
- duplicate reports can be collapsed by `(instance_id, root_cause_id)` while
  retaining all original findings.

The ledger also supports `write_blinded`/`from_blinded` and
`write_labels`/`import_labels`. The blinded package carries a commitment hash;
unknown fields and recursively embedded method/backbone/provider identity are
rejected. `write_json`/`load_json` round-trip the controlled ledger with a
ledger hash and reapply label, reconciliation, relabel and requirement-mapping
invariants. The CLI equivalents are `crossllm adjudication-export` and
`crossllm adjudication-import`; the latter imports labels only and does not
silently manufacture consensus.

The `FirstFailure` enum contains the 11 protocol classes: malformed
serialization, unresolved reference, type/domain mismatch, unwarranted
property, vacuity, duplication, solver infeasibility, timeout/unsupported,
replay failure, non-security behavior and true vulnerability. The existing
generated `dataset/benchmark/adjudication_records.jsonl` is not consumed as
ground truth by this implementation; it remains a synthetic fixture until the
independent corpus review is complete.

`scripts/generate_adjudication_records.py` is fail-closed for this reason. It
refuses to create records by default. With
`--allow-synthetic-template` it writes only pending templates with empty labels
and no reconciliation; those templates are workflow fixtures, not reviewer
evidence and cannot satisfy admission.
