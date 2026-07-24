# Metric Semantics

`docs/kpi_dictionary.md` (Phase 1) defined these indicators in business terms before any data model existed. This document grounds each one in the **operational entities from Phase 3** (`contracts/operational/*.yaml`) - which event or snapshot it comes from, at what grain, and what's still ambiguous. **No value is computed here** - there is no populated operational data yet (see `docs/synthetic_generation_spec.md`).

## Convention vs. standard

Every formula below is a **CredLens project convention**, stated so future code has one unambiguous definition to implement against - none of them is presented as a regulatory or universally-standard definition. Where a concept (DPD buckets, default) has genuine industry variation, that variation is called out explicitly.

## DPD (Days Past Due) - the project's convention

> **CredLens DPD convention**: the largest number of days past due among a contract's obligations (installments) that are past their `due_date` and still carry a positive outstanding amount, as of the reference date (`account_monthly_snapshots.snapshot_date`).

Formally, for a contract at `snapshot_date`:

```text
dpd = max(snapshot_date - installment.due_date for installment in contract.installments
          if installment.due_date < snapshot_date
          and installment.outstanding_balance > 0)
      else 0 if no such installment exists
```

Handling rules this convention commits to:

- **Partial payments**: an installment with `outstanding_balance > 0` still counts toward DPD even if partially paid - DPD is not waived by a partial payment.
- **Prepayment**: an installment paid *before* its `due_date` never contributes to DPD (it's excluded by the `due_date < snapshot_date` condition once it's also fully paid, and it was never overdue to begin with).
- **Reversals**: if a `payments` reversal reduces an installment's allocated amount back to a positive `outstanding_balance`, that installment re-enters the DPD calculation - a reversal can *increase* a contract's DPD, which is intentional (it reflects an obligation becoming unpaid again).
- **Multiple overdue installments**: DPD uses the **oldest** (largest days-overdue) obligation, not a sum - a contract with three overdue installments has one DPD number, driven by the earliest of the three.
- **No overdue obligation**: DPD is 0 (not null) - `account_monthly_snapshots.dpd` is `nullable: false` for exactly this reason.

This is implemented today only as the **bucket-consistency check** `dpd_matches_bucket` (`src/credlens/contracts/financial_rules.py`) - it verifies a stored `dpd`/`delinquency_bucket` pair are mutually consistent under the bucket convention below; it does not (yet) compute `dpd` from `installments`, because no generator populates `installments`/`account_monthly_snapshots` together yet.

### DPD buckets (CredLens convention, inclusive on both ends)

| Bucket | Range |
|---|---|
| `current` | `dpd = 0` |
| `1-29` | `1 <= dpd <= 29` |
| `30-59` | `30 <= dpd <= 59` |
| `60-89` | `60 <= dpd <= 89` |
| `90+` | `dpd >= 90` |

**DPD 30 / DPD 60 / DPD 90** (as used in `docs/kpi_dictionary.md`) mean "balance or count with `dpd >= 30 / 60 / 90`" - i.e. **cumulative** thresholds, not the discrete buckets above. A contract with `dpd = 45` counts toward "DPD 30+" and the `30-59` bucket simultaneously; these are two different, both-valid ways of slicing the same number, and any report must state which one it's using.

## Default - a configurable, versioned target (not fixed here)

> **Draft CredLens convention**: `90+ DPD within a performance window measured from origination` (window length not fixed - see below).

This is deliberately **not fully specified**, per this phase's brief:

- **Threshold**: 90+ DPD is the *draft* choice (common in the industry, not universal) - not locked in.
- **Window**: how many months from `contracts.contract_date` (or `disbursement_date`) the observation window covers is **unset**. A 12-month window and a 6-month window will classify different contracts as "default," particularly for longer-term loans.
- **Write-off treatment**: whether a `charged_off` contract counts as default regardless of its DPD history, or only if it independently crossed the 90+ DPD threshold first, is **unset**.
- **Immature contracts**: a contract younger than the observation window (e.g. 3 months old, with a 12-month window) cannot yet be labeled either "default" or "non-default" - it must be excluded or marked "not yet observable," never silently counted as a non-default.

**This target must be versioned** (e.g. `default_definition_version` alongside any future label table) precisely because the three choices above are business decisions, not facts - changing any of them changes which contracts are labeled "default" without changing anything about the contracts themselves. **No column in `application_features` may ever encode this label** - it is by definition only knowable after the observation window closes, long after the application decision it would otherwise leak into (see `docs/target_and_leakage_audit.md`).

## Indicator grounding

| Indicator | Source (event/snapshot) | Grain | Reference date | Numerator | Denominator | Key ambiguity |
|---|---|---|---|---|---|---|
| Application volume | `applications` (event: `submitted_at`) | one row per application | submission date | `COUNT(applications)` | — | Duplicate applications from the same customer - see `docs/kpi_dictionary.md`. |
| Approval rate | `credit_decisions` (event: `decision_timestamp`, `is_final=true`) | one row per application's final decision | decision date | `COUNT(outcome=approved)` | `COUNT(is_final=true)` | Same-day vs. eventual decision window. |
| Booking rate | `credit_decisions` (approved, final) joined to `contracts` | one row per approved application | contract/decision date | `COUNT(contracts)` | `COUNT(approved final decisions)` | Time lag between approval and contracting straddling a reporting period. |
| Average ticket | `contracts.financed_amount` | one row per contract | `contract_date` | `SUM(financed_amount)` | `COUNT(contracts)` | Mean sensitive to outliers - median recommended alongside. |
| Portfolio balance | `account_monthly_snapshots.total_balance` | one row per contract per month | `snapshot_date` | `SUM(total_balance)` | — (a stock, not a rate) | Must state the snapshot date; excludes `charged_off` balance by convention (see `cumulative_write_off` vs `total_balance`). |
| DPD / DPD 30/60/90 | `account_monthly_snapshots.dpd` | one row per contract per month | `snapshot_date` | see "DPD" above | — | See "DPD" section above. |
| First payment default | `installments` (installment_number=1) + `account_monthly_snapshots` | one row per contract | first installment's `due_date` | `COUNT(first installment DPD >= threshold)` | `COUNT(contracts with a first installment due)` | Threshold and observation window not fixed here - same open question as "Default" above. |
| Vintage | `contracts.contract_date` (cohort key) + `account_monthly_snapshots` (age = months since `contract_date`) | one row per contract per months-on-book | months-on-book, not calendar date | delinquent balance/count at age *m* | cohort balance/count at age *m* | Must align by months-on-book, not calendar date - see `docs/kpi_dictionary.md`. |
| Roll rate | `account_monthly_snapshots.delinquency_bucket` at consecutive `snapshot_date`s | one row per contract per bucket transition | month-over-month pair | count moving bucket X -> X+1 | count in bucket X at period start | Requires strictly monthly snapshot cadence - a gap breaks the transition matrix. |
| Cure rate | `account_monthly_snapshots.delinquency_bucket` at consecutive `snapshot_date`s | one row per contract per bucket transition | month-over-month pair | count moving bucket X -> current | count in bucket X at period start | "Partial cure" (paid down but not fully current) needs an explicit rule - not fixed here. |
| Recovery rate | `recovery_events.amount` vs. `write_off_events.amount` | one row per write-off, aggregated over its recoveries | recovery window from `write_off_date` | `SUM(recovery_events.amount)` | `write_off_events.amount` | Recovery has a long tail - reporting too soon after write-off understates it; window not fixed here. |
| Write-off rate | `write_off_events.amount` vs. `account_monthly_snapshots.total_balance` | aggregate over a period | period | `SUM(write_off_events.amount in period)` | average/beginning `total_balance` in period | Sensitive to the (currently undocumented) write-off policy threshold. |
| Expected loss | `PD x EAD x LGD` - no source table yet | n/a - no risk model exists | n/a | n/a | n/a | No PD/LGD model exists in Phase 3 - see `docs/roadmap.md` phase 9-10. Listed here only to note it is out of scope, not silently omitted. |
| Exposure | `account_monthly_snapshots.exposure` | one row per contract per month | `snapshot_date` | (a stored value, not yet derived from a formula) | — | Conceptually related to a future EAD calculation - not computed as EAD in this phase. |
| Revenue | `installments.scheduled_interest`/`scheduled_fees` (accrual) vs. `payment_allocations` (cash) | one row per contract per month (aggregated) | accrual or cash basis - must state which | `SUM(interest + fees)` | — | Accrual vs. cash basis diverges once delinquency rises - not fixed here. |
| Funding cost | no source table in this phase | n/a | n/a | n/a | n/a | Funding is a company-level fact, not a per-contract one - no `funding_sources` table exists in Phase 3's scope. |
| Contribution margin | Revenue - funding cost - credit losses | portfolio or segment level | monthly | derived from the above | — | Whether "credit losses" means expected (modeled) or realized (write-off) loss must be stated each time. |
| Risk-adjusted return | Contribution margin / a risk-weighted exposure measure | portfolio or segment level | monthly/quarterly | derived from the above | derived from the above | No single universal formula - the most methodologically open indicator in this list, per `docs/kpi_dictionary.md`. |

See `docs/kpi_dictionary.md` for the original business-facing definitions (pitfalls, stakeholders) - this table exists to connect those definitions to the concrete tables that would compute them, once populated.
