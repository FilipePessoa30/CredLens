# Fairness Data Design

This document covers the **design of `fairness_attributes`** for the future synthetic operational layer (`contracts/operational/fairness_attributes.yaml`). For the equivalent audit of the two real public datasets acquired in Phase 2 (UCI Default of Credit Card Clients, South German Credit), see `docs/sensitive_attributes.md` - that document is about data CredLens actually has; this one is about data it plans to generate.

## Why a separate table

`fairness_attributes` holds synthetic demographic-style fields (`age_bracket`, `synthetic_gender`, `region`) that a future model-fairness audit would need, kept in a table physically separate from `application_features` (the table a future model would actually train on). Every column in `fairness_attributes` is classified `evaluation_only` and `available_for_modeling: false` - see `docs/adr/0005-fairness-attribute-separation.md` for the decision record.

The mechanism this buys: it is structurally harder to accidentally join a sensitive attribute into a training set, because doing so requires explicitly joining a table whose name and classification say "evaluation only" - not a silent column that happens to sit next to legitimate features.

## What physical separation does NOT buy

**Separation is necessary, not sufficient.** It does not, by itself, prevent proxy discrimination:

- `application_features.declared_income`, `employment_months`, and `bureau_score_bucket` can each correlate with the attributes held in `fairness_attributes` (income and employment history correlate with age and region in most real populations; a synthetic generator that mimics realistic joint distributions would very plausibly reproduce this).
- A model trained only on `application_features` (which never sees `fairness_attributes` directly) can still reproduce disparate outcomes across the groups `fairness_attributes` would measure, purely through these correlated features.
- **This project does not claim, anywhere, that excluding a sensitive attribute from model features makes a model fair.** That claim is explicitly rejected here, matching `docs/sensitive_attributes.md`'s "Why exclusion alone proves nothing" section for the real datasets.

## What `fairness_attributes` is actually for

Once a model exists (a later phase - `docs/roadmap.md` phase 10+), `fairness_attributes` is the table an **outcome-rate/proxy audit** would join against model predictions or decisions, *after* the fact - comparing approval rates, PD estimates, or realized default rates across `age_bracket`/`synthetic_gender`/`region` groups. It is an audit input, not a training input, and not a promise that the audit has been run (it hasn't - no model exists yet).

## Deliberately abstract labels

`synthetic_gender` uses the values `a`/`b`/`unspecified`, not `male`/`female` - a reminder at the data-dictionary level that this is fictional generated data standing in for a demographic concept, not a real survey of real people. This mirrors the general rule in `docs/assumptions_and_limitations.md`: nothing in this project describes a real person.

## Small-group risk (a future concern, stated now)

Once populated, any cross-tabulation of `fairness_attributes` against outcomes will have some groups with very few rows, especially for scenarios with small synthetic populations (see `docs/synthetic_generation_spec.md`'s `population` parameters, all `requires_calibration`). A future fairness audit must report cell sizes alongside any rate, exactly as `docs/sensitive_attributes.md` already requires for the real UCI/South-German data - the same statistical-reliability caution applies regardless of whether the underlying data is real or synthetic.

## Country/period transportability (does not apply the same way here)

Unlike the real UCI (Taiwan, 2005) and South German Credit (Germany, 1970s) datasets, a future synthetic population is explicitly generated to resemble the *fictional* CredLens scenario (a present-day Brazilian digital lender) - so the "don't transport findings across countries/eras" caution from `docs/sensitive_attributes.md` doesn't apply in the same way. A different caution applies instead: **a finding from synthetic data is a fact about the generator's assumptions, not about real Brazilian applicants** - see `docs/assumptions_and_limitations.md`'s limitations on synthetic data.

## Auditing this design is not authorizing real use

Nothing in this document, `docs/sensitive_attributes.md`, or any fairness check this project ever implements constitutes a fairness certification or legal/regulatory clearance for real-world use - restated here because it is the single most important limitation for anything touching demographic data. See `docs/assumptions_and_limitations.md`.

## What a future phase must do before using `fairness_attributes` for anything

1. Populate it only via the synthetic generator (once built) - never with real data, per `docs/roadmap.md` and `SECURITY.md`.
2. Run a proxy-correlation check between `application_features` and `fairness_attributes` before claiming a model is "unaware" of sensitive attributes just because they weren't direct inputs.
3. Report cell sizes alongside any group-level rate.
4. Never produce a group-level credit decision or recommendation from this table - only aggregate, retrospective audit statistics.

## Phase 4B: a versioned allowlist enforcing this, not just convention

Phase 4A's generator already never read `fairness_attributes` when computing a
decision score - true by construction (the code simply never referenced it) but
not enforced as an explicit interface. Phase 4B adds
`credlens.generation.feature_allowlist.DECISION_FEATURE_ALLOWLIST` - a versioned,
module-level constant listing exactly the `application_features` columns the
decision score is allowed to read (`bureau_score_bucket`, `declared_income`,
`debt_to_income`). `credlens.generation.decisions.compute_decision_score` now
goes through `select_decision_features()`, the only sanctioned read path, which
also runs `assert_allowlist_is_safe()` - a check that the allowlist itself never
contains a column matching a forbidden pattern (`propensity`, `latent`, `truth`,
`dpd`, `write_off`, `payment`, `gender`, `age_bracket`, `region`, `fairness`).
This means a future column added to `application_features` (behavioral, or
accidentally copied from `fairness_attributes`) cannot silently start
influencing the score just by existing on the table - a change to
`DECISION_FEATURE_ALLOWLIST` itself is required, which is a reviewable code
change, not a data change. See `tests/test_generation_truth_isolation.py` for
the allowlist tests and a metamorphic test proving decisions are unaffected by
even an extreme perturbation of the (separately isolated) synthetic-truth layer.
