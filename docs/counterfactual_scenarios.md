# Counterfactual scenarios (Phase 4B)

Every claim in this document is about **this synthetic DGP's own behavior**, not
about any real lender, real applicant population, or real macroeconomic
relationship. "Approval increases when the cutoff is relaxed" is a fact about
`credlens.generation.decisions`'s scoring formula, proven by construction (see
`docs/common_random_numbers.md`) - not a claim about how any real institution's
approval rate would respond to a real policy change.

## Scope

Five scenarios became executable this phase (see
`credlens.generation.config.EXECUTABLE_SCENARIOS`):

| Scenario | What changes vs. baseline | CRN scenario? |
| --- | --- | --- |
| `policy_expansion` | `policy.approval_score_cutoff` lowered (0.5 → 0.35) | yes |
| `policy_tightening` | `policy.approval_score_cutoff` raised (0.5 → 0.65) | yes |
| `macroeconomic_stress` | A dated payment-behavior shock from `macro_shock.shock_date` onward | yes |
| `collections_change` | Collections intensity, cure probability, recovery odds | yes |
| `contract_coverage` | A small, deliberately extreme-parameter fixture forcing rare states | no (not a scenario, a test fixture) |

`data_quality_incident` remains `requires_calibration` as a *generation* config -
it is not a distinct DGP, but a controlled post-hoc corruption of an already-valid
run (see `docs/data_quality_incident.md`).

Each scenario's own `config/synthetic/<name>.generation.yaml` file documents
exactly which fields differ from `baseline.generation.yaml`, in a comment at the
top of the file.

## `policy_expansion` / `policy_tightening`

**Simplification vs. the blueprint.** `config/synthetic/scenarios/
policy_expansion.blueprint.yaml` (still `requires_calibration`) describes a
richer design: a second `policy_versions` row taking effect mid-period. What was
actually implemented is simpler - a single, whole-period cutoff change - because
section 6/7 of this phase's own prompt lists "cutoff" as sufficient on its own,
and a mid-period switch would need applications split by submission date against
two different cutoffs (a materially bigger change, deferred - see
`docs/synthetic_calibration.md`).

**Guarantee, proven not just intended**: because the decision score never reads
`policy.approval_score_cutoff` (see `docs/common_random_numbers.md`), baseline's
approved-application set is always a **subset** of `policy_expansion`'s, and
`policy_tightening`'s approved set is always a **subset** of baseline's -
verified in `tests/test_generation_scenarios_4b.py` and in every
`generate-suite` run's directional checks.

Booking, contracts, and payment behavior for whichever applications *do* get
approved are otherwise generated exactly as in baseline - a looser/stricter
policy changes *who* gets a contract, not how an approved contract behaves.

## `macroeconomic_stress`

A single dated shock (`macro_shock.shock_date`, `2024-07-01` in the shipped
config) is applied to `payment_behavior` from that month onward via
`credlens.generation.payments._effective_payment_behavior`: `on_time_probability`,
`partial_payment_probability`, `prepayment_probability`, and
`cure_probability_per_month` are each multiplied by a documented factor
(0.65/1.30/0.40/0.50 respectively) and clipped back into `[0, 1]`. Nothing else
changes - the origination/decision/booking/schedule code paths are completely
unaware a shock exists.

**Pre-shock identity** is a hard invariant: every payment settled before
`shock_date` is byte-identical to baseline's (verified by
`tests/test_generation_scenarios_4b.py::TestMacroeconomicStress` and by every
`generate-suite` run). **Post-shock direction** is a statistical claim, verified
via Monte Carlo across 10 seeds (`reports/synthetic_validation/
monte_carlo_summary.json`): DPD90+ increased in **10 of 10** seeds tested
(mean delta +0.065, stdev 0.017).

`macro_context_monthly` gains additional rows for the shock window
(`source_type=synthetic_shock`, `is_synthetic=true`, its own `source_id`) -
the real BCB rows already present are never modified, removed, or blended with
the synthetic ones (they differ in `source_type`/`source_id`, part of that
table's own primary key - see `docs/adr/0008-macro-context-provenance.md`).

## `collections_change`

Only `collections.contact_dpd_thresholds` (earlier contact),
`collections.promise_to_pay_probability`, `payment_behavior.
cure_probability_per_month`, and `recovery.*` differ from baseline - see the
comment in `collections_change.generation.yaml` for the specific values.

**Why this preserves pre-eligibility behavior without any code change**:
`cure_probability_per_month` is read in exactly one place,
`_decide_payment_amount`'s `has_backlog` branch - which, by construction, only
ever executes for a contract that *already* has an overdue installment (i.e. is
already collections-eligible per `should_contact`). Every payment a contract
makes *before* ever falling behind is governed by `on_time_probability`/
`partial_payment_probability`/`prepayment_probability`, none of which this
scenario touches. So "no change before collections eligibility" is a consequence
of this scenario being **config-only** (no code path was added or changed for
it), not something that needed a separate mechanism to enforce.

Monte Carlo confirms the intended direction: cure rate increased in the seeds
tested (`tests/test_generation_montecarlo.py`).

## `contract_coverage`

Not a scenario - a small (90-customer), deterministic, deliberately
extreme-parameter fixture whose only purpose is to force every rare state this
phase's tests need to see within a `smoke`-scale run in well under a second. See
`config/synthetic/contract_coverage.generation.yaml`'s own docstring for the
full list and `reports/synthetic_validation/contract_coverage.json` for which
states a real run actually produced.

### `contract_coverage` known gap - FIXED in Phase 5

Phase 4B's cure mechanism (`_decide_payment_amount`'s `has_backlog` branch)
paid off a contract's **entire remaining balance** on cure, not just its
overdue backlog - a deliberate Phase 4A simplification ("full cure: pay
everything open"). This made every cure terminal, so true relapse (delinquent
→ current → delinquent again, on the same still-open contract) was
architecturally impossible under any configuration of the generator, and
`contract_coverage` covered only 12 of its 13 target states.

**Phase 5 fixed this** - see `docs/adr/0010-cure-semantics-and-relapse.md`. A
cure now pays only the installments overdue as of the cure month
(`due_date < month_end`), leaving future not-yet-due installments untouched
and the contract non-terminal. `contract_coverage` now produces all 13 of 13
target states in a single real run, including relapse - proven, not just
configured, in `tests/test_generation_cure_semantics.py` and
`tests/test_generation_scenarios_4b.py::TestContractCoverage`. This was a
genuine DGP semantic change: `GENERATOR_VERSION` moved `"0.5.0"` →
`"0.6.0"`, every `*.generation.yaml`'s `version` field moved `1` → `2`, and
every scenario's canonical content hash changed - no attempt was made to
preserve the old (Phase 4A/4B) hashes, per this phase's own instructions.

## What was intentionally NOT built this phase

- A mid-period `policy_versions` switch (the blueprint's richer
  `policy_expansion`/`policy_tightening`/`collections_change` design).
- A "contacted → cure boost" mechanism keyed on individual collection contacts
  (the `collections_change` scenario models this as a scenario-level parameter
  shift instead - see above).
- Any scenario combining two interventions at once (e.g. stress + tightening).
