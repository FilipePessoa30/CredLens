# Business Rules

The full catalog of integrity rules from this phase's brief, organized by category, each marked with its real implementation status. **A rule is only marked "implemented" if real code exists and a fixture in `tests/fixtures/contracts/` exercises it** - see `docs/data_contracts.md` for how validation actually runs, and the Phase 3 final report for command-by-command evidence.

Legend: **Generic** = enforced automatically for any contract from its YAML schema (`src/credlens/contracts/domain_rules.py`), no per-rule code needed. **Named** = a specific function in `relational_rules.py` / `temporal_rules.py` / `financial_rules.py`, referenced by a contract's `business_rules[].code`. **Specified only** = documented here and in the relevant contract's `description`/comments, but no automated check exists yet.

## Identity (local rules)

| Rule | Status | Mechanism |
|---|---|---|
| IDs not null | **Implemented (generic)** | `check_nullability` - every `*_id` primary/foreign key column is declared `nullable: false`. |
| IDs unique at the declared grain | **Implemented (generic)** | `check_primary_key` / `check_uniqueness_rules`. |
| No ID resembles a real document number (CPF) | **Implemented (generic)** | `check_no_document_like_identifiers` - regex-checks every `*_id` column; see `SECURITY.md`. |
| No orphan foreign key | **Implemented (generic)** | `check_foreign_keys` - checks every declared `foreign_keys[]` entry against the referenced table, when supplied. |

## Applications and decisions (relational + temporal)

| Rule | Category | Status | Code / mechanism |
|---|---|---|---|
| Decision timestamp >= submission timestamp | Temporal | **Implemented** | `decision_not_before_submission` |
| At most one final decision per application | Relational | **Implemented** | `single_final_decision` |
| Rejection never produces a contract | Relational | **Implemented** | `contract_requires_approved_final_decision` |
| Approved amount not negative | Local | **Implemented (generic)** | `credit_decisions.approved_amount` domain `{min: 0}`. |
| Cancelled application cannot silently become a new contract without a new application | Relational | **Specified only** | No `applications` row is ever reused across contracts by construction (`contracts.application_id` is a single FK) - not independently re-checked as a named rule because the schema itself makes the violation structurally impossible to represent. |
| Policy valid at the decision instant | Temporal + relational | **Implemented** | `approval_requires_valid_policy` |

## Contracts

| Rule | Category | Status | Code / mechanism |
|---|---|---|---|
| Contract requires an approved, final decision | Relational | **Implemented** | `contract_requires_approved_final_decision` |
| Contract date >= decision timestamp | Temporal | **Implemented** | `contract_after_decision` |
| Disbursement date >= contract date | Temporal | **Implemented** | `disbursement_not_before_contract` |
| Term/installment count positive | Local | **Implemented (generic)** | `contracts.term_months`, `num_installments` domain `{min: 1}`. |
| Financed amount positive | Local | **Implemented (generic)** | `contracts.financed_amount` domain `{min: 0}`. |
| `status` is one of the documented state-machine values | Local | **Implemented (generic)** | `contracts.status` domain `in_set`, per `docs/state_machines.md`. |
| Individual status *transitions* are legal (e.g. no `settled -> active`) | State | **Specified only** | See `docs/state_machines.md`, "What is - and isn't - automatically enforced today" - would need an event-history table this phase doesn't build. |

## Installments

| Rule | Category | Status | Code / mechanism |
|---|---|---|---|
| Installment number unique per contract | Local | **Implemented (generic)** | `uniqueness_rules: installment_number_unique_per_contract`. |
| `scheduled_total = principal + interest + fees` | Financial | **Implemented** | `installment_total_reconciled` |
| Components not negative | Local | **Implemented (generic)** | domain `{min: 0}` on `scheduled_principal`/`scheduled_interest`/`scheduled_fees`. |
| `status` consistent with `outstanding_balance` | Financial + state | **Specified only** | See `docs/state_machines.md`'s "Installments" derivation note - a real gap, stated explicitly rather than silently assumed handled. |

## Payments

| Rule | Category | Status | Code / mechanism |
|---|---|---|---|
| Amount positive | Local | **Implemented (generic)** | `payments.amount` domain `{min: 0.01}`. |
| A reversal references an existing, earlier payment | Temporal | **Implemented** | `reversal_references_earlier_payment` |
| Allocations for a payment never exceed its amount | Financial | **Implemented** | `payment_allocation_not_exceed_payment` |
| An allocation never crosses contracts | Relational | **Implemented** | `allocation_same_contract` |
| Allocated components reconcile to the allocation total | Financial | **Implemented** | `allocation_total_reconciled` |
| Allocated amounts not negative | Financial | **Implemented** | `allocation_amount_not_negative` (redundant with the generic domain check, kept as an explicit financial-reconciliation precondition per this phase's brief). |

## Snapshots

| Rule | Category | Status | Code / mechanism |
|---|---|---|---|
| `(contract_id, snapshot_date)` unique | Local | **Implemented (generic)** | primary key + `uniqueness_rules: contract_month_unique`. |
| `total_balance = principal + interest + fees` | Financial | **Implemented** | `total_balance_reconciled` |
| `dpd` not negative | Local | **Implemented (generic)** | `account_monthly_snapshots.dpd` domain `{min: 0}`. |
| `delinquency_bucket` consistent with `dpd` | Financial | **Implemented** | `dpd_matches_bucket` (CredLens bucket convention - see `docs/metric_semantics.md`). |
| `cumulative_paid` non-decreasing (absent a documented reversal) | Financial | **Implemented, `warning` severity** | `cumulative_paid_non_decreasing` |
| `cumulative_write_off` non-decreasing | Financial | **Implemented, `error` severity** | `cumulative_write_off_non_decreasing` |
| No snapshot exists after a contract's status is first observed as terminal | Temporal | **Implemented (Phase 4A)** | `no_snapshot_after_terminal_status` - the fix that replaced the Phase 3 fixture's `DPD=999` sentinel; see `docs/adr/0009-dpd-sentinel-removal.md`. |
| `cumulative_paid` reconciles against the payments/allocations ledger | Financial | **Implemented (Phase 4A)** | `snapshot_cumulative_paid_reconciled` - closes the Phase 3-declared gap ("cumulative_paid is not reconciled against payments"). |
| `total_balance` reconciles against installments/payments/allocations, net of write-off | Financial | **Implemented (Phase 4A)** | `snapshot_balance_reconciled_with_ledger` |
| `cumulative_write_off` reconciles against `write_off_events` | Financial | **Implemented (Phase 4A)** | `snapshot_write_off_reconciled` |
| `dpd` reconciles against installments' real due dates (never a sentinel) | Financial | **Implemented (Phase 4A)** | `snapshot_dpd_reconciled_with_installments` - the mechanical rejection of a fabricated DPD like the old `999`. |

## Collections and write-off

| Rule | Category | Status | Code / mechanism |
|---|---|---|---|
| Collections event references an existing contract | Relational | **Implemented (generic FK)** | `collection_events.contract_id` foreign key. |
| Write-off date >= contract date | Temporal | **Implemented** | `write_off_not_before_contract` |
| Write-off amount reconciles to principal + interest + fees | Financial | **Implemented** | `write_off_amount_reconciled` |
| Recovery date >= its write-off's date | Temporal | **Implemented** | `recovery_after_write_off` |
| Write-off never deletes/rewrites prior events | Relational (structural) | **Implemented by construction** | Every table is append-only in this schema (no `UPDATE`/`DELETE` concept exists in a contract-validated CSV/JSON snapshot) - there is nothing in the schema that *could* rewrite history, so there is no dedicated rule to bypass. |
| Promise-to-pay fields internally consistent | Financial | **Implemented** | `promise_fields_require_promise_flag` |

## BCB raw-source rules (Phase 2 debt, automated in Phase 3)

| Rule | Status | Code / mechanism |
|---|---|---|
| Observation dates unique | **Implemented (generic)** | `primary_key: [data]` on `bcb_sgs_20570`/`bcb_sgs_21112`. |
| Observation dates strictly increasing (chunking-boundary regression) | **Implemented** | `bcb_dates_strictly_increasing` - see `docs/data_contracts.md` for the real bug this automates the regression test for. |
| `EDUCATION`/`MARRIAGE` values within UCI's documented domain | **Implemented (generic)** | `uci_default_credit.yaml` column domains - see `docs/data_quality_audit.md` for the finding this automates. |

## Macro/market context (Phase 4A)

| Rule | Category | Status | Code / mechanism |
|---|---|---|---|
| `is_synthetic`/`series_code` agree with `source_type` | Relational | **Implemented (Phase 4A)** | `macro_context_provenance_consistent` - see `docs/adr/0008-macro-context-provenance.md`. |

## Summary

As of Phase 3, **22 rules were implemented as real, dispatchable business-rule functions**. Phase 4A added **6 more** (`no_snapshot_after_terminal_status`, the four `snapshot_*_reconciled` ledger-reconciliation rules, and `macro_context_provenance_consistent`), bringing the total to **28** (`registry.KNOWN_BUSINESS_RULE_CODES` - verified by running `len(KNOWN_BUSINESS_RULE_CODES)`, not estimated), plus the generic schema-driven checks (nullability, domain, PK, FK, uniqueness, CPF-pattern) that apply to every contract automatically. **3 are explicitly specified but not yet automated** (policy-window overlap across rows, full state-transition replay, installment-status/balance consistency) - each is named above and cross-referenced to the document explaining why, rather than silently assumed to be covered.

**Phase 4B added no new business rules** (still 28) - instead, `credlens.generation.quarantine` proves 5 of the *existing* rules (`PK_DUPLICATE`, `FK_ORPHAN`, `DOMAIN_VIOLATION`, `SNAPSHOT_AFTER_TERMINAL_STATUS`, `DECISION_BEFORE_SUBMISSION`) actually catch their corresponding defect when it occurs in generator-shaped data, not just in hand-authored fixtures - see `docs/data_quality_incident.md`. `generation_runs` moved to contract version 3: its `scenario` domain gained `contract_coverage`, its `status` domain gained `quarantined_expected_failure`, and it gained two new nullable columns (`suite_id`, `parent_run_id`) for Phase 4B's counterfactual suites - no new business-rule *function* was needed for any of this, only domain/schema widening.
