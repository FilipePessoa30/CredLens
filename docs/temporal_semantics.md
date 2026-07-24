# Temporal Semantics

This document defines every timestamp/date role used across `contracts/operational/*.yaml`, and the causal-order rules that `src/credlens/contracts/temporal_rules.py` and `relational_rules.py` enforce. It applies to the future synthetic operational layer (not yet generated - see `docs/synthetic_generation_spec.md`) and, where relevant, to the raw public sources.

## Timestamp/date roles

Each column in a contract YAML declares a `temporality` value from this list (or `null` if it plays no special temporal role):

| Role | Meaning | Example columns |
|---|---|---|
| `event_timestamp` | The instant a fact became true - the anchor for an event row. | `applications.submitted_at`, `credit_decisions.decision_timestamp`, `contracts.contract_date`, `customers.created_at`, `collection_events.event_timestamp` |
| `effective_from` / `effective_to` | Start/end of a validity window for a versioned entity. | `policy_versions.effective_from`/`effective_to`, `generation_runs.period_start`/`period_end` |
| `snapshot_date` | The reference date a point-in-time snapshot describes - not an event. | `account_monthly_snapshots.snapshot_date`, `macro_context_monthly.reference_date` |
| `due_date` | A contractual obligation date, independent of whether it was met. | `installments.due_date`, `contracts.first_due_date`, `account_monthly_snapshots.next_due_date`, `collection_events.promised_date` |
| `payment_date` | When a payment was made (may differ from `settlement_date`). | `payments.payment_timestamp` |
| `settlement_date` | When a payment actually cleared/settled. | `payments.settlement_date` |
| `write_off_date` | When a write-off event occurred. | `write_off_events.write_off_date` |
| `as_of_date` | Not currently used by any Phase 3 contract - reserved for a future "state as of an arbitrary date" query, distinct from the fixed monthly `snapshot_date` cadence. | (none yet) |
| `ingested_at` | When CredLens itself retrieved/loaded a fact (a technical timestamp, not a business one). | `macro_context_monthly.retrieved_at` |
| `generated_at` | When a synthetic generation run executed (wall-clock, technical). | `generation_runs.generated_at` |

## Rules

- **Technical timestamps are UTC.** `generated_at`, `ingested_at`, and any column typed `timestamp` are compared as UTC-aware values - `src/credlens/contracts/temporal_rules.py` parses every timestamp comparison with `pd.to_datetime(..., utc=True)` specifically so a column that happens to be entirely empty (and would otherwise default to a timezone-naive dtype) never silently breaks a comparison against a timezone-aware one. This was a real bug caught and fixed during this phase's own fixture testing - see the Phase 3 final report.
- **Contractual dates (`due_date`, `write_off_date`, `snapshot_date`, etc.) are plain dates**, not timestamps - they don't carry a time-of-day or timezone, by design (a due date is a calendar date, not an instant).
- **Validity intervals must not overlap for the same entity.** `policy_versions` rows for the same `name` must have non-overlapping `[effective_from, effective_to)` windows - not yet enforced as an automated rule in this phase (only single-row `effective_to > effective_from` is checked, via `policy_validity_window_not_inverted`); overlap-across-rows is a documented gap for a later phase, not silently assumed away.
- **The policy applicable to a decision is the one valid at the decision instant.** `approval_requires_valid_policy` checks `effective_from <= decision_timestamp < effective_to` (or `effective_to` is null, meaning still in force).
- **Features are frozen at the proposal instant.** `application_features.feature_snapshot_at` must equal `applications.submitted_at` - no column in `application_features` may ever be filled from information that postdates that instant. See `docs/adr/0004-feature-freeze-at-proposal.md`.
- **No information flows backward in time.** Nothing computed at time T may depend on a row whose own `event_timestamp`/`snapshot_date` is after T. This is the general principle `decision_not_before_submission`, `contract_after_decision`, `disbursement_not_before_contract`, `write_off_not_before_contract`, and `recovery_after_write_off` each enforce for one specific pair of tables.
- **Monthly snapshots do not replace events.** `account_monthly_snapshots` is a derived, point-in-time view - it must be consistent with the event tables (e.g. `cumulative_paid` should reconcile with `payments`/`payment_allocations` once a generator exists) but is never the source of truth for *when* something happened.
- **A write-off never rewrites history.** Every row that existed before a `write_off_events` entry (installments, payments, snapshots) stays exactly as it was; only new rows (the write-off itself, and any later recovery) are added.

## Causal order (minimum chain)

```text
customer
  -> application
    -> credit_decision
      -> contract
        -> installment schedule
          -> payment behavior (payments, payment_allocations)
            -> monthly snapshot
              -> collection_event
                -> write_off_event
                  -> recovery_event
```

This is a **minimum** chain, not a strict requirement that every contract passes through every stage - see "Valid exceptions" below.

## Valid exceptions (a shorter or branched chain is not automatically invalid)

- **Cancelled application**: `customer -> application` only; no decision, no contract.
- **Approved but never activated**: `customer -> application -> credit_decision (approved)`; no contract - approval does not imply contracting.
- **Rejected application**: `customer -> application -> credit_decision (rejected)`; no contract, ever - enforced by `contract_requires_approved_final_decision`.
- **Prepayment**: a contract can reach `settled` well before its scheduled final installment - the chain still holds (payments still follow the schedule causally), just compressed in time.
- **Partial payment**: one `payments` row can leave an installment still `partially_paid` - `payment_allocations` may show less than the full `scheduled_total` allocated.
- **Reversed payment**: a `payments` row with `reversal_of_payment_id` set must have a *later* `payment_timestamp` than the original it reverses (`reversal_references_earlier_payment`) - the chain briefly "moves backward" in balance terms but never in the timestamps themselves.
- **Renegotiation**: not yet modeled as its own event type in Phase 3's contracts (no `renegotiation_events` table exists) - a documented gap, not a silent omission; see `docs/synthetic_generation_spec.md` open questions.
- **Recovery after write-off**: the chain's last two steps are optional and, when present, must stay ordered (`recovery_after_write_off`) - most written-off contracts will have zero recovery rows.
