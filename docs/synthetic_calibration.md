# Synthetic calibration (Phase 4B)

This document classifies every parameter introduced or changed by Phase 4B's
five scenario configs, using the four categories this phase's own prompt
requires:

- **`synthetic_assumption`** - a chosen, documented, not-otherwise-justified
  value (the same posture every Phase 4A baseline parameter already has - see
  `docs/assumptions_and_limitations.md`).
- **`benchmark_informed`** - loosely informed by a public, non-institutional
  reference point, without claiming to reproduce it.
- **`derived_from_public_aggregate`** - computed from a real public data series
  already acquired by this project (BCB SGS).
- **`counterfactual_intervention`** - not a calibration target at all; the
  value exists specifically to define *what changes* in a counterfactual, and
  its "correctness" is that it's clearly documented, not that it matches
  anything real.

**None of these parameters are claimed to be calibrated from a real
institution.** This document exists to be explicit about *why* each value is
what it is, not to claim any of them are validated business assumptions - see
the hard constraints below.

## Hard constraints (unchanged from Phase 4A, restated for this phase's new parameters)

- No parameter here claims institutional calibration.
- No scenario reproduces a real portfolio.
- No sensitive attribute (`fairness_attributes`) is adjusted to imitate a real
  population - Phase 4B does not touch `fairness_attributes` generation at all.
- UCI and BCB data are never joined at the individual/customer level.
- BCB aggregate series are never used as an individual-level target.
- Every numeric parameter lives in a `config/synthetic/*.generation.yaml` file,
  never hardcoded in generator source.

## Parameter classification

### `policy_expansion.generation.yaml` / `policy_tightening.generation.yaml`

| Parameter | Value | Classification | Why |
| --- | --- | --- | --- |
| `policy.approval_score_cutoff` (expansion) | 0.35 (was 0.5) | `counterfactual_intervention` | Chosen to move a meaningful fraction of the score distribution from rejected to approved (160→250 of 307 smoke-scale applicants) without approving everyone - not a claim about a real credit policy's actual threshold. |
| `policy.approval_score_cutoff` (tightening) | 0.65 (was 0.5) | `counterfactual_intervention` | Symmetric choice, same reasoning (160→52 approved). |
| Every other field | unchanged from baseline | (inherits baseline's own classification) | Required for CRN - see `docs/common_random_numbers.md`. |

### `macroeconomic_stress.generation.yaml`

| Parameter | Value | Classification | Why |
| --- | --- | --- | --- |
| `macro_shock.shock_date` | 2024-07-01 | `synthetic_assumption` | Chosen to split the simulated year roughly in half, giving both a pre-shock identity window and a post-shock direction window to test - not tied to any real event date. |
| `macro_shock.on_time_probability_multiplier` | 0.65 | `synthetic_assumption` | Chosen to produce a clearly measurable, but not total, degradation - tuned by re-running Monte Carlo until DPD90+ moved consistently across seeds (10/10) without collapsing the whole portfolio into delinquency at `smoke` scale. |
| `macro_shock.partial_payment_probability_multiplier` | 1.30 | `synthetic_assumption` | Same tuning process - a modest shift toward partial rather than full payment. |
| `macro_shock.prepayment_probability_multiplier` | 0.40 | `synthetic_assumption` | Households prepay less under stress is a directionally reasonable synthetic assumption, not a calibrated elasticity. |
| `macro_shock.cure_probability_multiplier` | 0.50 | `synthetic_assumption` | Same tuning process. |
| `macro_shock.synthetic_shock_value` | 1.0 | `synthetic_assumption` | An illustrative, unitless index level recorded on the synthetic `macro_context_monthly` rows - explicitly not a real macroeconomic indicator value, and not itself read back by the payment simulation (only `shock_date` is). |
| The pre-existing real BCB series (`bcb-sgs-20570`, `bcb-sgs-21112`) this scenario still carries through unmodified | - | `derived_from_public_aggregate` | Unchanged from baseline - real BCB SGS observations, re-expressed at the operational grain, never invented (`credlens.generation.macro`). |

The shock multipliers were **not** derived from any real stress-testing model or
historical Brazilian macro shock - they are round numbers chosen to produce a
measurable, monotonic, testable effect. A future phase wanting a
`benchmark_informed` version of this scenario would need to anchor the
magnitude to some public reference (e.g. a published historical NPL-during-
recession range) while still not claiming to reproduce it exactly.

### `collections_change.generation.yaml`

| Parameter | Value | Classification | Why |
| --- | --- | --- | --- |
| `collections.contact_dpd_thresholds` | `[7, 25, 55]` (was `[15, 45, 75]`) | `synthetic_assumption` | Roughly halved, to represent "more proactive" outreach - not from any real collections playbook. |
| `collections.promise_to_pay_probability` | 0.55 (was 0.35) | `synthetic_assumption` | Chosen to produce a clearly higher promise-to-pay rate. |
| `payment_behavior.cure_probability_per_month` | 0.38 (was 0.20) | `synthetic_assumption` | Tuned so cure rate increases consistently across Monte Carlo seeds without approaching 1.0. |
| `recovery.recovery_probability` / `recovery_fraction_min` / `recovery_fraction_max` | 0.45 / 0.10 / 0.55 (was 0.25 / 0.05 / 0.40) | `synthetic_assumption` | Same reasoning - a better collections process recovering more, and more per case, is a directionally reasonable assumption, not a calibrated recovery curve. |

### `contract_coverage.generation.yaml`

Every parameter in this file is `synthetic_assumption` by construction - it is
explicitly a test fixture with deliberately extreme values (see
`docs/counterfactual_scenarios.md`), never presented as a plausible population.

## What remains `requires_calibration`

The blueprint files under `config/synthetic/scenarios/*.blueprint.yaml` still
mark several design questions unresolved for every scenario (customer arrival
pattern, applications-per-customer distribution, segment mix, seasonality) -
Phase 4B's executable configs inherit baseline's own already-`specified` answers
to these (see `config/synthetic/scenarios/baseline.blueprint.yaml`) without
resolving the remaining `pending`/`requires_calibration` items. `data_quality_incident`
has no executable generation config at all - see `docs/data_quality_incident.md`
for why it doesn't need one.
