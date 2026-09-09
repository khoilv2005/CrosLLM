# Review and acceptance policy deviation

Date: 2026-09-09  
Decision owner: project owner  
Implementation agent: Codex

## Decision

This workspace proceeds with only two participants: the project owner and the
implementation agent. A separate second reviewer, external benchmark reviewer,
or independent sign-off is not a required gate for engineering checklist items.

Each checklist item instead requires an objective evidence bundle:

- implementation diff or commit reference;
- relevant tests, validator output, or reproducible report;
- artifact/input hashes where applicable;
- explicit limitations and deviation notes; and
- owner acceptance with a date.

Codex performs an implementation self-check and reports failures fail-closed.
The project owner makes the final acceptance decision. No acceptance record may
be described as an independent review.

## Scope and limitation

This is a workflow deviation from the Experiment Guide's independent-review
expectation. It removes a staffing blocker; it does not create independent
ground truth, independent Q/trigger validation, or independent adjudication.
Reports must preserve this limitation, and publication/evaluation claims that
require independent review remain out of scope until the owner explicitly
revises the claim or supplies an independent reviewer.

The deviation does not waive objective reproducibility checks, source/build
provenance, hash validation, security boundaries, or the rule that missing
evidence remains `PENDING`/`UNKNOWN` rather than being inferred as a pass.
