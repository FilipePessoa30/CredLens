# ADR 0003: Hybrid Event/State/Snapshot Architecture

## Status

Accepted.

## Context

A credit portfolio needs to answer both "what happened, and when" (e.g. exactly when a payment was made) and "what did the book look like at month-end" (e.g. the balance and DPD at each monthly close). A single table cannot serve both needs well: an events-only design makes "what was the balance on 2024-06-30" an expensive replay of every prior event; a snapshots-only design loses the exact sequence and timing of individual facts (which payment came from which channel, which collections contact preceded a promise-to-pay).

## Decision

Model three distinct kinds of table, never collapsed into one:

- **Events** (`applications`, `credit_decisions`, `contracts` activation, `payments`, `collection_events`, `write_off_events`, `recovery_events`) - one row per fact that happened at an instant (`event_timestamp`).
- **Current state** (`contracts.status`, `installments.status`) - the entity's own record of where it stands right now, updated as events occur.
- **Snapshots** (`account_monthly_snapshots`, `macro_context_monthly`) - a point-in-time fact table, keyed by a reference date, that never substitutes for the event tables it's derived from.

See `docs/temporal_semantics.md` for the full role definitions and `docs/conceptual_data_model.md` for how the three interact across the four ER diagrams.

## Alternatives considered

- **Events only, compute snapshots on demand.** Rejected for this phase: correct in principle, but requires a computation/materialization layer (dbt or equivalent) that doesn't exist yet (`docs/architecture.md`'s `Transform`/`Warehouse` layers are still "planned"). Storing snapshots directly, with contract-level consistency rules (`total_balance_reconciled`, `dpd_matches_bucket`), gets useful monthly-close data modeled now without waiting on that later layer.
- **Snapshots only, no event tables.** Rejected: loses exactly the information collections/payment-allocation analysis needs (which payment paid which installment, which collections strategy preceded which outcome) - see `docs/kpi_dictionary.md`'s roll-rate, cure-rate, and recovery-rate definitions, all of which need event-level granularity.
- **One single wide table mixing event and snapshot columns.** Rejected explicitly by this phase's brief ("Não use uma única tabela para representar incorretamente eventos e estados") - it would make the table's grain ambiguous and its uniqueness/reconciliation rules unstatable.

## Consequences

- Every table's grain is unambiguous and stated in its contract (`grain:` field) - a direct benefit visible in `docs/conceptual_data_model.md`'s entity table.
- A future transformation phase (dbt) has a clean event-sourcing-style foundation to build derived marts from, rather than needing to first untangle a mixed-grain table.
- Consistency between events and snapshots (e.g. `account_monthly_snapshots.cumulative_paid` vs. summed `payments`) is not yet cross-checked (no rule joins snapshot cumulative fields back to the event tables that should produce them) - a stated gap, not a silent one; see `docs/business_rules.md`.

## Risks

- Without the cross-check named above, a future generator could produce internally inconsistent events and snapshots undetected until a later phase adds that rule.
