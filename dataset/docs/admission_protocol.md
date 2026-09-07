# Admission protocol

## Purpose

This protocol prevents public incident lists from being misrepresented as contamination-resistant LLM generalization evidence. The unit of analysis is a bridge/version or a validated mutant instance, nested in a protocol lineage; it is never an arbitrary contract file.

## Historical candidate workflow

1. Start from a public inventory record.
2. Confirm the incident is an in-scope smart-contract or message-validation failure rather than a key compromise, governance takeover, or non-executable external endpoint.
3. Identify relevant source and destination artifacts; pin commits, compiler settings, addresses, bytecode hashes and chain pair.
4. Construct an isolated harness and replay only a safety-reviewed trigger.
5. Obtain independent ground-truth support from at least two evidence sources when practical.
6. Locate a patched or benign matched control and record its relationship.
7. Assign the complete lineage to `development` or `evaluation` before prompt/model tuning.
8. Promote the record to `admitted`; otherwise preserve it as `candidate` or mark it `rejected` with a reason.

## Sealed evaluation workflow

1. Select an official EVM-to-EVM host lineage with a reproducible build and paired harness.
2. Split host lineages before designing prompts, models, or hyperparameters.
3. Apply a semantics-changing, property-mapped mutation.
4. Independently validate reachability and the expected XLIR property violation.
5. Create a clean matched control using the same harness and comparable source shape.
6. Store mutant source and exact trigger outside the public package until all evaluation runs are frozen.
7. Publish manifest identifiers, hashes, generator version, aggregate results and release policy; publish full material later only after disclosure review.

## Required statuses

| Status | Meaning | May enter paper results? |
|---|---|---|
| `candidate` | Source lead; missing one or more admission gates. | No |
| `admitted` | All required artifacts and validation evidence are present. | Yes |
| `rejected` | Out of scope or irreproducible; retain reason. | No |
| `sealed_pending` | Intended sealed item whose source/trigger validation is unfinished. | No |
| `sealed_ready` | Validated sealed item; source/trigger withheld under embargo. | Yes, after experiment freeze |

## Safety rule

Do not include mainnet-drain payloads, private keys, RPC credentials or deployment instructions in the public dataset. Replay must run in an isolated local/fork environment with no broadcast capability.
