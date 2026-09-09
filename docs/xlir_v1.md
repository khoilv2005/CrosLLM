# XLIR v1 proposal contract

XLIR v1 is the typed, grounded proposal format implemented in `src/crossllm/xlir/`. Its structural contract is recorded in `schemas/xlir_proposal.schema.json`; the compiler adds grounding, type, finite-domain and semantic checks that JSON Schema cannot express. It accepts a single JSON object from a proposer. It is a validation boundary, not a proof engine and not a security-property adjudicator.

## Public symbol table

`crossllm xlir-validate` accepts either a JSON list or an object containing `symbols`. Every entry must have `symbol_id`, `path`, `name`, `domain`, `kind`, and `type`. Supported types are `bool`, `uint256`, `int256`, `address`, and `bytes32`; domains are validated by the artifact-builder contract as `source`, `destination`, or `shared`.

```json
{
  "symbols": [
    {
      "symbol_id": "sym.source.locked_amount",
      "path": "Bridge.sol",
      "name": "lockedAmount",
      "domain": "source",
      "kind": "storage",
      "type": "uint256"
    }
  ]
}
```

## Proposal grammar

An explicit abstention is valid and retained as a consumed proposal slot:

```json
{"abstain": true, "reason": "No grounded invariant is available."}
```

An invariant contains a Boolean expression. Symbol references must name a public symbol and specify `pre` or `post` state.

```json
{
  "kind": "invariant",
  "invariant_id": "value-conservation",
  "body": {
    "kind": "binary",
    "operator": "eq",
    "left": {"kind": "symbol", "symbol_id": "sym.source.locked_amount", "state": "post"},
    "right": {"kind": "literal", "type": "uint256", "value": 0}
  }
}
```

Expression kinds are `symbol`, `literal`, `unary`, `binary`, `bound`, `quantifier`, and `temporal`. Unary operations are `not`, integer `neg` (signed only), and integer `bitnot`. Boolean binary operations are `and`, `or`, and `implies`; equality operations are `eq` and `neq`; ordering operations are `ge`, `le`, `gt`, and `lt`; checked arithmetic operations are `add`, `sub`, `mul`, `div`, and `mod`. Integer bit-vector operations are `band`, `bor`, `bxor`, `shl`, `shr` (logical unsigned shift), and `sar` (arithmetic signed shift). Ordering and arithmetic/bitwise operations require equal `uint256` or equal `int256` operands; shift amounts are `uint256`; signed arithmetic is range-checked rather than silently wrapped, and division/modulo by zero is invalid. Equality requires equal operand types; an invariant root must be Boolean. Quantifiers require an explicitly enumerated finite literal domain, and temporal operators are `once` (with a non-negative horizon) and `globally`.

The compiler rejects unknown symbol IDs, unsupported types, invalid state annotations, type mismatch and ASTs beyond the configured limit. It returns a canonical AST hash after grounding. The current `Z3XLIRBackend` can execute the grounded finite core for counterexample and antecedent queries. Finite quantifiers are expanded over their declared literal domains, and temporal operators are expanded over an explicitly supplied trace length. Results retain explicit `SAT`, `BOUNDED_UNSAT`, `UNKNOWN`, `UNSUPPORTED` and `CRASH` outcomes, timeout and cancellation handling, and model extraction. This is still an SMT core only: it does not assess security legitimacy, encode bounded dual-chain transitions, or replay a witness on an independent EVM.

The method runner uses this canonical AST identity for semantic duplicate
scheduling when the parser returns a compiled invariant (or a serialized
invariant carrying its verified `canonical_hash`). Every ordered proposal slot
is still retained in the denominator; raw serialization hashes are only a
fallback identity and are not reported as semantic diversity. Slot records
expose `canonical_ast_hash` for downstream audit without turning a duplicate
into a new finding.

The `primitive` expression kind is syntax sugar for the same core. Supported
IDs are `justified_destination_effect`, `replay_exclusion`,
`quorum_authorization`, `proof_binding`, `callback_noninterference`,
`challenge_window` and `intent_consumption`; each has a fixed argument arity.
Expansion happens before grounding, so unresolved references and type errors
remain compiler diagnostics. A primitive and its equivalent generic expression
produce the same canonical body hash, making the primitive-vs-generic ablation
explicit rather than introducing a second semantic engine.

`XLIRLowerer` also produces a deterministic solver-neutral IR with explicit
bit-vector/Boolean sorts, stable symbol names, node IDs and a source map back
to XLIR paths. Quantifier expansion and temporal indexing are visible in this
IR. The Z3 adapter currently translates the typed AST directly so that the
solver-neutral IR remains an inspectable contract; backend integration with the
source-host dual-chain transition model is still pending.

`assess_legitimacy` is a conservative structural gate: by default it requires
grounded source and destination observations in both pre- and post-state, but
it reports `security_validity=not_assessed`. It is therefore an eligibility
check for independent property review, not a security oracle. For vacuity,
`check_antecedent_transition` evaluates the implication antecedent over
explicit transition traces and returns `BOUNDED_UNSAT` only when both the trace
set and the transition exploration are declared complete; empty traces,
missing bindings and incomplete exploration remain `UNKNOWN`.

For tiny concrete fixtures, `evaluate_invariant` evaluates a compiled invariant
against explicit `(symbol_id, state, domain)` bindings, while `evaluate_trace`
applies finite-trace temporal semantics at index zero. Missing bindings,
cross-state/domain lookups, invalid widths and uint256/int256 overflow/underflow are
reported as evaluation errors; they are not converted into a false result. This
is a differential-test helper, not an EVM execution result.

Run it with the installed package, or with `PYTHONPATH=src` during development:

```bash
crossllm xlir-validate --symbols symbols.json --proposal proposal.json
```

Storage layouts can provide a starter symbol table without guessing domains:

```bash
crossllm extract-storage-symbols \
  --artifact-root dataset/artifacts/hop \
  --domains domains.json
```

`domains.json` explicitly maps each selected contract to `source`, `destination`, or `shared`. The extractor keeps only losslessly supported scalar storage fields (`bool`, `uint256`, `int256`, `address`, `bytes32`) and reports mappings, arrays, structs, and narrower integer widths as skipped. A future typed accessor language must model those fields before admitting them to XLIR.
