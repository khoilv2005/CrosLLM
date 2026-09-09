# M08 development Cloud proposal collection

Date: 2026-09-09  
Status: `COMPLETED_DEVELOPMENT_PROBE`; non-admission.

## Scope

The development-only campaign runner was exercised against the canonical
Ollama Cloud endpoint using the existing local `.env`. It read the public
source-backed ChainBridge artifact pack, the frozen T0 prompt asset, and the
previously archived gpt-oss preflight response. No local model weights were
used, no sealed data was read, and no second reviewer was required by the
project workflow policy.

The run selected one campaign (`chainbridge`, `T0`, `gpt-oss`) from a bundle
with one campaign. It consumed eight ordered proposal slots and completed
with two compiled candidates, zero invalid slots, zero provider failures, and
response identity `gpt-oss:120b-cloud`.

## Reproduction and hashes

The executable input bundle was prepared with:

```powershell
.venv\Scripts\python.exe scripts\prepare_development_campaign.py `
  --out-dir build\development_campaign_chainbridge_gpt_v3 `
  --lineages chainbridge --families gpt-oss --methods T0
```

The bundle plan hash is
`bb5464023661243a350bf17c394c50a06f2c5bb1cd3dfea99e0255254ad52704` and the
bundle manifest hash is
`d05a19b3efa262a86db447eafb342b9948a8446005abf6c2ffd2dde946e48113`.
The preflight archive hash is
`fe7953b57ac15ff7464388de05e0cda17285b9a8c56824d401775580a9924ead`.

The run report is retained in the ignored controlled workspace path
`build/development_campaign_chainbridge_gpt_v3/run-smoke/` with these internal
and file hashes:

- `report.json`: internal `report_hash` `02da27b8cf4a148f2cdc0fe44454b2fd47c076d00deee0b72a6ebbc67af3b028`; file SHA-256 `31f120a2c0fb1a887f8da03b87b33231d9e022264881b816fa2100e1584e67e3`
- `events.jsonl`: file SHA-256 `70d76970477870eab93e42e48881587391f2860bebff5cf3e27f94077fd72174`
- `runs.jsonl`: file SHA-256 `20bd79c1f79233df62c9bf3c14deb14d3f1eb6c3336196f5884cfee5fc901f00`

The event ledger contains 20 records, including one terminal campaign event.
The run is reproducible only while the ignored build bundle and preflight
archive are retained locally; these hashes do not turn it into admission
evidence.

After adding the in-campaign response-model identity guard, the same bounded
smoke was rerun at
`build/development_campaign_chainbridge_gpt_v3/run-smoke-v2/`. It again
completed 1 campaign and 8 calls with 2 compiled candidates, 0 invalid slots,
0 provider failures and 20 events. Its report internal hash is
`7d27ad481502f6beb27597619a9deda51991727f0a6a1ebab79c59b8c8f679d6`; the
report, event and run file SHA-256 values are respectively
`aea3fa94e091a0b2e5afa936ccd19e33afbbd3628e5d7a7aa65fb6de92b466d6`,
`4cb7ff8b142f722f59ffa73c37cfedba83d3c23044ffa3df7a435484ce0499c6`, and
`a4822c40cae2feb625d1c52dae9fb77160d8ed7ee70aa1afbaf32de514fb462e`.

A second source-backed smoke used LayerZero v2 (three extracted primitive
storage symbols) with the same T0/gpt-oss settings. It completed 1 campaign
and 8 calls with 3 compiled candidates, 5 duplicate slots, 0 invalid slots,
0 provider failures and response identity `gpt-oss:120b-cloud`. The bundle
plan hash is
`993e25d8a875b19c7753489cd6c62e63dc7a942f03d331b6acc5119f78a05369`; its
run report hash is `0a874aef7f95c1960e0cc3677e200609d2b5be8fb69d7747af9991c625ce6d29`,
with report/event/run file hashes
`f37bb047919b0968bcdd79c88b1a99ed143f72b62b64e90bb52535f37fdf5a5c`,
`272107beb35ecb7aad78912e4e7ec138b7e19d0717dee7fd9b4678d07e55d7e6`, and
`00527ccf3c4d142047671175152f45c523edaf6c2d37d19b5acf95a7e8b836d5`.

## Boundary and limitations

This is proposal collection only. It does not execute native EVM search or
replay, evaluate security legitimacy, adjudicate gold labels, or establish an
immutable served-weight digest/effective-settings attestation. The local
controller also does not claim Docker firewall enforcement. The result is
therefore development evidence that the Cloud transport, slot accounting,
public symbol grounding, compilation path, event persistence, and terminal
status path work end-to-end; it is not an evaluation result.
