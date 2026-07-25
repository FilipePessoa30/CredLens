# ADR 0009: No Sentinel DPD Values - Retention Rule Instead

## Status

Accepted.

## Context

The Phase 3 `valid_minimal_scenario` fixture used `dpd=999` on a charged-off contract's final monthly snapshot, as a stand-in for "this account is no longer meaningfully aging." That is exactly the kind of magic-number sentinel this project's own conventions elsewhere reject (see `SECURITY.md`, `docs/business_rules.md`'s identity rules on not using placeholder-shaped values). It also had no basis in the ledger: nothing computed 999 from any due date or payment history - it was simply written into the fixture by hand.

## Decision

Two changes together eliminate the need for any DPD sentinel:

1. **Retention rule**: once a contract's status is first observed as terminal (`settled`/`closed`/`charged_off`) in a monthly snapshot, no later `snapshot_date` may exist for that contract - enforced by the new `no_snapshot_after_terminal_status` temporal rule. The terminal month's own snapshot is simply the last one generated; there is never a "month after write-off" snapshot that would need a placeholder DPD.
2. **Ledger-derived DPD, always**: `dpd` must equal the real, computed value - `max(snapshot_date - due_date)` over installments still carrying a positive outstanding balance as of `snapshot_date` (the formula already documented, but not automated, in `docs/metric_semantics.md`). This is now mechanically checked by `snapshot_dpd_reconciled_with_installments`, reconstructed independently from `installments`/`payments`/`payment_allocations`. Write-off does not reset or freeze this value - DPD is a fact about payment timeliness, not about the accounting treatment applied afterward; a written-off contract's terminal snapshot still reports the real elapsed days.

## Alternatives considered

- **Freeze DPD at the value observed on the write-off date, for snapshots after write-off.** Considered (explicitly offered as an option in this phase's brief) - not adopted, because it still requires deciding whether snapshots continue past write-off at all, and if they do, invites the same "what do the other balance fields show" ambiguity the retention rule avoids by construction. Simpler to just stop generating snapshots once a contract is terminal.
- **A null DPD after write-off, relying on `nullable` semantics.** Rejected: `account_monthly_snapshots.dpd` is `nullable: false` by design (see `docs/metric_semantics.md`, "No overdue obligation: DPD is 0, not null") - overloading null to mean "no longer applicable" would conflict with that existing, deliberate convention.

## Consequences

- No contract, fixture, or generator code needs a documented magic number for "delinquency after terminal status" - the retention rule removes the situation that would need one.
- The DPD formula documented since Phase 3 (`docs/metric_semantics.md`) is now actually implemented and mechanically checked, not just written down - closing that phase's stated gap.
- `tests/fixtures/contracts/valid_minimal_scenario` was rewritten with complete, small installment schedules (not partial ones) so `dpd`/`cumulative_paid`/`total_balance` can be genuinely ledger-reconciled - see `docs/adr/0007` for the general principle that fixtures must be honest, not just superficially plausible.

## Risks

- The reconciliation rule assumes `installments`/`payments`/`payment_allocations` are complete for a contract; a fixture or generator bug that omits an installment will make the reconciliation *silently* compute a smaller-than-real balance instead of failing loudly, because the rule has no way to know an installment is missing. Mitigated by the generator itself being the single source that produces installments (see `docs/synthetic_generation_implementation.md`), not hand-authored per contract.
