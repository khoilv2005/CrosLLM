# Development calibration and budget boundary

`src/crossllm/calibration/planning.py` implements a development-only selection
rule. `build_compact_calibration_menu` constructs exactly two reasoning levels
crossed with two temperatures around the starting setting, before any outcome
is read. The selector rejects any evaluation observation, requires complete
development measurements, filters by truncation and recall tolerance, then
chooses the lowest estimated cost deterministically and emits a selection hash.
The budget estimator includes main campaigns, baselines, calibration, retries,
solver core-hours and adjudication effort. Expected retry attempts multiply
provider calls, input/generated token estimates and provider cost (fractional
totals are rounded up for conservative planning); provider cost remains `null`
when rates are not supplied.

`calibration/simulation.py` simulates the actual hierarchy with unequal lineage
sizes and paired binary outcomes `(both, left-only, right-only, neither)`. It
reports seeded Monte Carlo standard errors for recall and paired differences.
With `--replicate-candidates 5 10 20`, the CLI evaluates the prespecified menu
and selects the smallest common `R` meeting both MCSE targets; if none does, it
returns an explicit precision limitation instead of silently choosing the
largest candidate.

The precision result reports three separate quantities: the numerical Monte
Carlo standard error of the simulation estimate, the conditional design
standard deviation implied by the configured campaign/instance/lineage
hierarchy, and the population spread of configured lineage expectations. The
common-R selector uses the conditional design SD against the declared recall
and paired-difference targets; the Monte Carlo SE only diagnoses whether the
simulation itself used enough draws. Lineage spread is a heterogeneity
diagnostic, not extra independent sample size; none of these quantities is a
substitute for lineage-level inference on observed evaluation data.

These are planning/development tools. No evaluation outcome or current public
synthetic benchmark row is used to select a setting, and no resulting number is
a measured CrossLLM result.

`freeze_development_selection` writes a hash-addressed development freeze that
binds the selected setting to protocol, prompt, primitive, mutation, harness,
runtime and analysis-code hashes. It rejects missing inputs and any evaluation
observation IDs, so the artifact is suitable as a pre-evaluation lock input but
does not itself certify an evaluation-ready corpus.

`SelectionDecision` now carries the selected/eligible setting definitions and
the complete development observation provenance. Duplicate observations for a
setting are rejected. JSON codecs in `calibration/io.py` re-run the selection
rule and verify its hash before a freeze can be loaded. The CLI workflow is:

```text
crossllm calibrate-select --settings settings.json --observations development.json --out selection.json
crossllm budget-estimate --inputs budget.json --out budget-estimate.json
crossllm calibrate-simulate --config precision.json --probabilities probabilities.json --out precision.json
# Optional development-only R selection from the prespecified menu:
crossllm calibrate-simulate --config precision.json --probabilities probabilities.json \
  --replicate-candidates 5 10 20 --out replicate-selection.json
crossllm calibrate-freeze --selection selection.json --hashes code-hashes.json --out development_selection.json
```

These commands produce planning/development artifacts only; `calibrate-freeze`
cannot accept evaluation observations and does not unlock the G3 gate.

`scripts/run_development_calibration_rehearsal.py` exercises the complete
development-only path and writes
`dataset/reports/m10_development_calibration_rehearsal.json`. It is explicitly
synthetic and records `executed_provider_calls: 0`; its menu, ten-call fixture,
conditional precision simulation, budget and freeze hashes are pipeline
evidence, not measured model outcomes.
