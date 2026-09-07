# Dataset status ledger

## Current verified progress

| Gate | Count | Status |
|---|---:|---|
| Historical candidate records | 6 | Candidate inventory only |
| Historical cases admitted to evaluation | 0 | Not started: requires artifact, replay and control evidence |
| Locked protocol lineages | 16 | Complete initial partition: 4 development, 12 evaluation |
| Source snapshots retrieved and content-hashed | 3 | Hop, Celer cBridge and ChainBridge |
| Paired EVM harnesses | 0 | Not yet built |
| Sealed validated positives | 0 | Not yet constructed |
| Distinct matched negative controls | 0 | Not yet constructed |
| Evaluation-ready cases | 0 | No experiment may be run yet |

## Blocking gates

The dataset will remain non-evaluable until every selected case has a source/bytecode/proxy configuration, reproducible paired harness, independent property and trigger validation, and a matched clean control. The target counts in the experiment guide are not substituted with repeated mutants, contract dependencies, or variants from the same lineage.

## Next construction batch

1. Finish source pinning for the four development lineages.
2. Build a local paired EVM harness and compiler/differential-execution checks for each.
3. Define development-only mutation operators and matched control construction.
4. Use development results to lock mutation/harness policy.
5. Repeat acquisition on the twelve evaluation lineages without changing prompt/model settings.
