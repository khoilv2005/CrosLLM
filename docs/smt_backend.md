# Grounded XLIR Z3 backend

`src/crossllm/backends/smt.py` provides the first concrete solver adapter for
the grounded XLIR core. It is intentionally narrower than the eventual
CrossLLM engine: it handles the current Boolean, uint256,
address and bytes32 AST, while dual-chain transition semantics, EVM execution,
proxy initialization and independent replay remain separate work.

The adapter exposes two queries:

- `check_violation`: asks whether the invariant body can be false;
- `check_antecedent`: for a root implication, asks whether its antecedent is
  satisfiable.

`crossllm.xlir.check_antecedent_smt` maps the latter query into the existing
vacuity contract. A satisfiable antecedent is `REACHABLE`; an exhausted
finite formula is `BOUNDED_UNSAT`; timeout is `TIMEOUT`, while cancellation,
unsupported encoding and solver failures remain `UNKNOWN`/`CRASH` with their
raw backend status in the reason. A shared campaign budget can be carried into
each query through `campaign_elapsed_seconds`.

Unsigned arithmetic is checked as Solidity-style bounded arithmetic by adding
no-overflow/no-underflow constraints. Results carry the solver version, query
hash, elapsed time, optional model, completeness flag and an explicit status.
`BOUNDED_UNSAT` means that the finite expanded bit-vector formula was
exhausted. It does not mean that a real bridge execution space was exhausted.

Development example:

```bash
crossllm xlir-smt-check \
  --symbols symbols.json \
  --proposal proposal.json \
  --query violation \
  --timeout-seconds 30
```

The dependency is pinned to `z3-solver==5.1.0.0` in `pyproject.toml` and the
observed import/version is recorded in `containers/toolchain.lock.json`.
