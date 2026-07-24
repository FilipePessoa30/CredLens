# ADR 0002: Adoption of a Synthetic Operational Data Layer

## Status

Accepted (decided in Phase 1/2 as strategy, formalized as a concrete schema in Phase 3).

## Context

CredLens's KPI scope (`docs/kpi_dictionary.md`) includes portfolio, vintage, roll-rate, collections, and profitability metrics that require a genuinely longitudinal loan portfolio: multiple monthly snapshots per contract, delinquency-bucket transitions, collections actions, write-offs, and recoveries over time. Neither acquired public dataset provides this: `uci_default_credit` is a single 6-month snapshot embedded as columns (no true time series), and `south_german_credit` is a single cross-sectional snapshot with no time dimension at all (see `docs/dataset_selection.md`, `docs/data_quality_audit.md`'s structural-limitation findings).

## Decision

Build a reproducible, code-generated synthetic operational layer (`contracts/operational/*.yaml`, sixteen tables) to fill this structural gap, clearly and mechanically distinguished from public data at every level (see `docs/data_strategy.md`'s synthetic/public labeling approach, and `generation_runs.is_synthetic`). This phase (3) specifies the schema and validation rules; generation itself is deferred to a later phase.

## Alternatives considered

- **Find a third public dataset with genuine longitudinal structure.** Considered in `docs/dataset_selection.md`; not pursued because none of the evaluated candidates (including the blocked Home Credit dataset) provide the specific vintage/roll-rate/collections structure CredLens's KPI scope needs, and acquiring a fourth individual-level dataset would add another country/era to reconcile (see ADR 0001) without solving the core gap.
- **Skip vintage/roll-rate/collections analysis entirely, scope down to what public data supports.** Rejected: this is exactly the analysis a credit-risk portfolio project is expected to demonstrate (see `docs/project_charter.md`), and dropping it would hollow out the project's core value proposition.
- **Build the generator immediately, without a schema/contract phase first.** Rejected: generating data against an undefined, unvalidated schema risks producing internally inconsistent output with no way to detect it - the contracts-first approach (this phase) ensures a generator (a later phase) has something real to validate against from day one.

## Consequences

- A real generator (Phase 4+) has a pre-validated target schema and a working validation harness (`credlens contracts validate --mode strict`) to check its own output against, rather than building both simultaneously.
- No portfolio-level KPI in `docs/kpi_dictionary.md` can be computed until the generator exists - `docs/metric_semantics.md` documents this gap per-indicator rather than implying readiness.
- The synthetic/public distinction must be enforced mechanically (directory separation, `is_synthetic` flags, git-ignore rules once real files exist) - not left to convention, per `docs/data_strategy.md`.

## Risks

- A synthetic generator's realism is only as good as its design assumptions - `docs/assumptions_and_limitations.md` already states synthetic data cannot be used as evidence about real-world credit-risk relationships, and this ADR does not change that.
- Schema drift between this phase's contracts and whatever a future generator actually needs is possible - mitigated by the contracts' explicit `evolution_policy` fields and semantic versioning.
