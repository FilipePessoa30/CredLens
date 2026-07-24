# State Machines

The Phase 3 brief proposed starting-point state machines for applications, contracts, and installments. This document does **not** accept them unreviewed - each is examined below, kept, narrowed, or extended, with the reasoning stated. **What `credlens.contracts` actually enforces automatically today is narrower than what's specified here**: it checks that a stored `status` value is one of the documented valid values (a domain check) and that specific causal orderings hold (the temporal/relational business rules) - it does not yet replay an event history to verify every individual transition was legal. That gap is stated explicitly at the end of this document, not hidden.

## Applications

```text
submitted -> under_review -> approved | rejected | cancelled
```

**Kept, with one addition and one clarification:**

- **Addition**: `submitted -> cancelled` directly (an applicant can withdraw before review even starts, not only mid-review).
- **Clarification on "revisions"**: the brief asks how manual review/revision is handled. This model does **not** add extra application-level states for that - instead, `credit_decisions` already allows multiple decision *events* per application (e.g. an automated rejection followed by a manual-override approval), with the rule that at most one may be `is_final=true` (`single_final_decision`). The application's own `status` column reflects only the outcome of that one final decision; the review history lives in `credit_decisions`, not as additional application states. This keeps the application state machine simple while still supporting revision as a relational fact.

**Terminal states**: `approved`, `rejected`, `cancelled`. **Invalid transitions**: any transition out of a terminal state (an application cannot un-reject or un-cancel itself - a customer who wants to try again submits a *new* application, per `contract_requires_approved_final_decision`'s framing that a contract traces back to one specific application's final decision).

## Contracts

```text
pending_activation -> active -> delinquent -> active -> settled | closed | charged_off
```

**Reviewed and revised** - the original proposal under-specifies several real paths:

```text
pending_activation -> active
pending_activation -> closed            (approved/contracted but disbursement never happened - deal fell through)
active -> delinquent
delinquent -> active                    (cure)
active -> settled                       (full payoff, on schedule or early - see below)
delinquent -> settled                   (payoff while delinquent, e.g. lump-sum/debt settlement)
active -> closed                        (rare administrative closure, not a payoff and not a charge-off)
delinquent -> charged_off               (the common path to charge-off)
active -> charged_off                   (uncommon - skips delinquent - not blocked, but expected rare)
```

- **Cure is explicit and bidirectional** (`active <-> delinquent`), matching the brief's requirement to consider cure.
- **`settled` covers both on-schedule and early payoff** - there is no separate "early settlement" status; if that distinction matters later, it should be derived by comparing `closed_date` to the original schedule (`installments.due_date` for the last installment), not stored as a second status.
- **Renegotiation is explicitly not modeled** as its own status or event table in this phase - see `docs/temporal_semantics.md`'s "valid exceptions" list. Adding it would require a new `renegotiation_events` table (new contract terms superseding the original schedule) that Phase 3 does not build; this is a documented gap for `docs/roadmap.md` phase 4, not something silently assumed to not matter.
- **A recovery after charge-off does not move the contract back to `active` or `delinquent`.** `charged_off` is terminal for `contracts.status` even if `recovery_events` rows exist afterward - the recovery is tracked as its own fact, not as a reversal of the charge-off.

**Terminal states**: `settled`, `closed`, `charged_off`. **Invalid transitions**: any transition out of a terminal state.

## Installments

```text
scheduled -> due -> partially_paid | paid | overdue
overdue -> paid | written_off
partially_paid -> paid | overdue | written_off
```

**Kept, with a derivation note the brief specifically asked for**: `due`, `overdue`, `partially_paid`, and `paid` are conceptually **derivable** from `due_date` (vs. the current date) and the sum of `payment_allocations` for that installment (vs. `scheduled_total`) - they should never be set independently of those facts once a generator/ETL exists. Phase 3 still declares `status` as a stored column on `installments` (`contracts/operational/installments.yaml`) because there is no derivation layer yet, but this is flagged as a **specification gap**: no business rule in this phase cross-checks `installments.status` against `outstanding_balance`/allocations for internal consistency (unlike `account_monthly_snapshots.dpd`/`delinquency_bucket`, which *is* cross-checked by `dpd_matches_bucket`). A later phase should add an equivalent `installment_status_matches_balance` rule before this table is ever populated by a real generator.

**Terminal states**: `paid`, `written_off`. **Invalid transitions**: `paid -> anything` (a fully paid installment does not un-pay itself - a later reversal would need to be modeled as new `payments`/`payment_allocations` rows referencing this installment again through a reversal payment, not a state change here).

## What is - and isn't - automatically enforced today

| Enforced automatically (`credlens contracts validate`) | Specified here, not yet enforced automatically |
|---|---|
| A stored `status` value is one of the contract's documented domain values (e.g. `applications.status in {submitted, under_review, approved, rejected, cancelled}`) - a `DOMAIN_VIOLATION` finding otherwise. | That a specific transition (e.g. `rejected -> approved`) never occurred - this would require replaying an ordered event history per entity, which no Phase 3 table stores (there is no `application_status_history` table). |
| Several specific causal/relational consequences of these state machines - e.g. `contract_requires_approved_final_decision` (a contract cannot exist unless its application's final decision was `approved`), `recovery_after_write_off` (a recovery cannot precede its write-off). | General "no terminal state re-enters a non-terminal state" checking across all three machines - only the specific named rules above are implemented; this is a reasonable extension for `docs/roadmap.md` phase 4, once a real event history exists to check it against. |

This split is intentional, not an oversight: Phase 3 implements exactly the rules it can genuinely verify against the tables that exist, and documents the rest as specified-but-not-yet-automated rather than silently claiming full state-machine enforcement that isn't really there.
