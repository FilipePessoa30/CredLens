# Common random numbers (CRN) - Phase 4B

## What this guarantees

For the same seed, scale, and period, `baseline` and every scenario in
`credlens.generation.config.CRN_SCENARIOS` (`policy_expansion`,
`policy_tightening`, `macroeconomic_stress`, `collections_change`) produce
**byte-identical** `customers`, `application_features`, and `fairness_attributes`
tables, and an `applications` table identical in every column except `status`
(which legitimately differs for `policy_expansion`/`policy_tightening`, since
those scenarios change which applications get approved). This is what makes a
baseline-vs-scenario comparison meaningful: any difference downstream of
population/application generation is attributable to the scenario's own
documented intervention, not to a different underlying sample.

`contract_coverage` is deliberately **excluded** from CRN - it is its own small,
extreme-parameter fixture (see `config/synthetic/contract_coverage.generation.yaml`),
never meant to be compared to baseline as a population.

## Why this works without extra machinery

`credlens.generation.rng.RunRandomStreams` already derives one independent numpy
`Generator` per named step (`customers`, `applications`, `decisions`, `booking`,
`payments`, ...) from a single seed via `numpy.random.SeedSequence(seed).spawn(N)`,
in a fixed order (Phase 4A). Independent substreams mean the `customers` stream's
draws never depend on what the `decisions` or `payments` streams later do - so
as long as two scenario configs are identical on every population/application-
affecting field, the customer arrival times, application counts/timing/channel,
declared income, bureau bucket, and fairness attributes are already guaranteed
identical, with **no extra CRN-specific code needed** for those steps.

The synthetic decision **score** itself (`credlens.generation.decisions.
compute_decision_score`) never reads `policy.approval_score_cutoff` - it is a
pure function of `application_features` (via the allowlist, see
`docs/fairness_data_design.md`) and the `decisions` RNG stream. Two scenarios
that differ *only* in `policy.approval_score_cutoff` therefore compute the exact
same score per application; only the `score >= cutoff` comparison differs. This
is what makes `policy_expansion`'s approved set a **superset** of baseline's,
and `policy_tightening`'s a **subset** - proven, not just intended - see
`docs/counterfactual_scenarios.md`.

## Two things that had to be fixed for CRN to actually hold

Two real bugs were found (empirically, by generating real suites and diffing
tables, not by reasoning alone) before CRN genuinely held:

1. **Id prefixes were scenario-specific.** `credlens.generation.ids.IdFactory`
   prefixes every id with a short hash of the run's own `config_hash` -
   deliberately, so re-running the *same* config twice produces the *same* ids
   (Phase 4A). But two *different* scenario configs (different policy/payment
   behavior values) have different `config_hash` values even when their
   population fields are identical - so `customer_id`/`application_id` came out
   as different strings across scenarios even when every other column matched.
   Fixed in `credlens.generation.orchestrator.generate_scenario`: for a CRN
   scenario, the `customer` and `application` id factories reuse **baseline's**
   short hash instead of the scenario's own. Every other id factory (decision,
   contract, installment, payment, ...) still uses the scenario's own short
   hash, since those entities are exactly what a scenario is allowed to make
   different.

2. **An unrelated config-schema addition churned every scenario's config hash.**
   Adding the (baseline-unused) `macro_shock` optional field to `GenerationConfig`
   changed `canonical_config_hash`'s output for *every* scenario, including
   ones that never set it - because the JSON payload gained a new
   `"macro_shock": null` key. Fixed by excluding unset optional fields from the
   hash (`model_dump(mode="json", exclude_none=True)`) - a config's hash now
   only reflects what it actually configures.

## How to verify CRN for a specific suite

```bash
credlens synthetic generate-suite --scale smoke --seed 2026
credlens synthetic validate-suite --suite-id SUITE_smoke_2026
```

`validate-suite` re-runs strict contract validation on every run in the suite
and prints each scenario's `population_crn_preserved` flag plus its directional
checks. The suite manifest itself (`reports/synthetic_validation/suites/
SUITE_<scale>_<seed>.json`) records the population table hashes used for that
comparison, the full config diff against baseline, and every metric delta - see
`reports/synthetic_validation/README.md`.

## What is NOT guaranteed

Downstream entities (decisions, contracts, installments, payments, collection
events, write-offs, recoveries) are **not** required to be identical across
scenarios - their ids, counts, and content are exactly what a scenario's
intervention is allowed to change. `macroeconomic_stress` payments are only
guaranteed identical to baseline's for months *before* the configured
`shock_date` (see `docs/counterfactual_scenarios.md`); `collections_change`
payments are only guaranteed identical for the pre-delinquency portion of a
contract's life (governed by `on_time_probability`/`partial_payment_probability`/
`prepayment_probability`, none of which that scenario touches).
