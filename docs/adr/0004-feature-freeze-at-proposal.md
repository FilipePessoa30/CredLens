# ADR 0004: Feature Freeze at the Proposal Instant

## Status

Accepted.

## Context

A credit-granting model can only ever use information that was genuinely available at the moment a decision was made. If a future model-training step reads "current" customer attributes (e.g. today's `customers`/`contracts` state) instead of what was known at `applications.submitted_at`, it would train on information from the future relative to the decision it's modeling - a severe, easy-to-introduce form of target leakage. `docs/target_and_leakage_audit.md` (Phase 2) found exactly this class of problem in `uci_default_credit` (18 of 23 variables are post-origination behavioral data, unusable for an origination model).

## Decision

`application_features` is a separate table from any "current state" table, populated (once a generator exists) only with values as they stood at `feature_snapshot_at = applications.submitted_at`, never updated afterward. No later phase's ETL/model-training code may substitute a live/current lookup for this table.

## Alternatives considered

- **Compute features on demand from current state, filtered by date.** Rejected: requires every future consumer to correctly implement "as of" filtering against every source table, every time - a much easier mistake to make than reading one already-frozen table. `application_features` centralizes the freeze so the leakage-prevention logic exists in exactly one place, not reimplemented at every use site.
- **Store features as columns directly on `applications`.** Rejected: conflates the application EVENT (what was submitted) with the DECISION INPUT (what was known) - `docs/business_rules.md` and this project's general events/snapshots ADR (0003) both argue against collapsing distinct concepts into one table.

## Consequences

- Any future model-training pipeline that reads `application_features` is safe from this specific leakage class by construction, provided it never joins in additional "current" data.
- `application_features` duplicates `requested_amount`/`requested_term_months` from `applications` (documented as intentional in the contract) specifically so a model-training query never needs to join back to `applications` at all, reducing the chance of an accidental additional join pulling in post-decision fields.

## Risks

- This ADR protects against **temporal** leakage (using future information) but not **structural** leakage (using a variable that, even at decision time, encodes information that shouldn't be available, like `debt_to_income` calculated from a source the applicant hasn't actually authorized) - a separate concern `docs/target_and_leakage_audit.md` addresses per-dataset, not solved by the freeze mechanism alone.
- If a future generator's implementation is careless, it could still populate `application_features` from post-decision information at generation time (the contract can check *values* are internally consistent but cannot verify the generator's own internal data flow) - this remains a code-review concern for whoever builds the generator, not something `credlens contracts validate` can detect from the output alone.
