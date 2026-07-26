# ADR 0010: Cure semantics - backlog-only, not full payoff

## Status

Accepted (Phase 5).

## Context

Phase 4A's `credlens.generation.payments._decide_payment_amount` modeled
"cure" of a delinquent contract as a single binary event: if a contract had
any overdue installment, the ONLY two outcomes each month were "pay off the
contract's entire remaining balance" (cure) or "pay nothing." The comment
on that code path was explicit about the simplification: `# full cure: pay
everything open`.

This had a real, documented consequence, discovered while building Phase
4B's `contract_coverage` test fixture: because a cure always drained a
contract's `total_open` to exactly zero, the very next check
(`total_open <= tolerance`) always classified the contract as `"settled"` -
terminal - in the same month. A cured contract could never be observed
active again, and therefore could never become delinquent a second time.
Phase 4B's own final report listed this as a known, architectural gap:
`contract_coverage` covered 12 of its 13 target states, and "delinquency
relapse" was the one state no configuration of the generator could produce.

## Decision

A cure now pays exactly the sum of the contract's installments that are
overdue **as of the snapshot instant** (`due_date < month_end` - the same
strict boundary `credlens.generation.snapshots.compute_dpd` and
`derive_snapshot_row`'s `past_due_amount` already use to decide what counts
as "vencido"), and nothing more. Installments due later
(`due_date >= month_end`) are left completely untouched - still scheduled,
still capable of being paid on time, missed, or (if missed) becoming a new
backlog in a later month.

Concretely, in `_decide_payment_amount`'s `has_backlog` branch:

```python
# before (Phase 4A/4B)
if rng.random() < cure_chance:
    return min(total_open, total_open)  # pays EVERYTHING open

# after (Phase 5)
if rng.random() < cure_chance:
    overdue_now = [i for i in active_installments if due_dates[i.installment_id] < month_end]
    cure_amount = sum((i.remaining_total for i in overdue_now), Decimal("0"))
    return cure_amount, "cure"
```

This makes "cure" mean exactly what section 3.1 of this phase's own
instructions define it as: *the transition from a situation with an overdue
amount to a situation with no overdue amount* - `past_due_amount` and `dpd`
both return to `0` at the cure month's own snapshot, while `total_balance`
and future installments are otherwise unaffected. The contract's status
after a cure is computed by the SAME status-determination code that already
existed (`total_open <= tolerance` → settled; else `should_write_off` →
charged_off; else `dpd > 0` → delinquent; else → `active`) - no new status
branch was added. Since `total_open` after a partial cure is normally
still positive (there are remaining future installments), the contract
naturally comes out `"active"`, not terminal.

A **prepayment** remains architecturally distinct and unchanged: it is only
ever reachable from the *non-backlog* branch (a contract with nothing
currently overdue), and it still pays `total_open` in full - every
remaining installment, due or not. A cure and a prepayment can now produce
numerically identical amounts only by coincidence (a cure that happens to
be paid on a contract's very last remaining installment) - they are always
reachable via different code paths, driven by different random outcomes,
and (new in Phase 5) tagged with different `payment_type` values.

### `payment_type`, an explicit event classification

`payments.payment_type` (`contracts/operational/payments.yaml`, version
1→2) now records, per payment row, exactly which of `scheduled` (on-time),
`partial`, `cure`, or `prepayment` produced it - the generator's own
classification at the moment of the event, never inferred afterward from
amount heuristics. A reversal row carries the same `payment_type` as the
payment it reverses. This directly answers section 3.1's requirement for
an *explicit* separation between payment kinds, and gives any downstream
consumer (including the Phase 5 warehouse) a reliable way to identify cure
events without reconstructing them from snapshot status transitions.

### Relapse is derived, not stored

Section 3.2 explicitly asks for relapse to be identifiable "without adding
redundant operational columns if the information can be derived from
events and snapshots." No new column was added to `account_monthly_snapshots`
or `contracts` for this. Relapse (delinquent → cured/active → delinquent
again, same contract) is fully reconstructable from the existing
`account_monthly_snapshots.status` time series ordered by
`(contract_id, snapshot_date)` - which is exactly what
`tests/test_generation_cure_semantics.py::TestRelapse` and, in the
warehouse, `int_reincidence` do.

## Consequences

- **Hashes change.** This is a genuine DGP behavior change, not a
  refactor - `global_content_hash` for every scenario, at every scale,
  differs from Phase 4A/4B's recorded values, deliberately. Per this
  phase's own instructions, no attempt was made to preserve the old
  hashes.
- **Every `*.generation.yaml`'s `version` field was bumped 1 → 2** (no
  parameter value changed) specifically so `config_hash` - and therefore
  `generation_run_id` - changes even for scenarios whose numeric
  assumptions are identical to before. This guarantees a Phase 5 run is
  written to a NEW directory, never silently overwriting a Phase 4
  run at the same path.
- **`GENERATOR_VERSION` bumped `"0.5.0"` → `"0.6.0"`** in
  `credlens.generation.orchestrator`, recorded in every run's
  `generation_runs.generator_version` - the authoritative, per-run record
  of which cure semantics produced that run's data. A consumer (e.g. the
  warehouse) can and should check this field before treating two runs as
  comparable.
- **`contract_version_set` corrected** from a stale, never-updated
  `"phase4a-v1"` literal to `"phase5-v1"`, reflecting that `payments`
  moved to contract version 2 this phase.
- Old Phase 4A/4B run directories under `data/synthetic/` and
  `data/synthetic_truth/` are untouched - they simply now sit alongside,
  not underneath, any new Phase 5 run directory (different
  `generation_run_id`).
- `contract_coverage` now produces all 13 of its target states in a single
  real run (`reports/synthetic_validation/contract_coverage.json`,
  regenerated this phase) - see `docs/counterfactual_scenarios.md`'s
  updated "known gap" section.
- Reconciliation is unaffected by construction: cure still only ever
  reduces installment `remaining_*` fields via the same
  `allocations.allocate_payment` function every other payment type uses,
  so `credlens.contracts.financial_rules`' four independent, output-side
  reconciliation rules (`snapshot_cumulative_paid_reconciled`,
  `snapshot_balance_reconciled_with_ledger`,
  `snapshot_write_off_reconciled`, `snapshot_dpd_reconciled_with_installments`)
  apply unchanged and still pass in strict mode.

## Alternatives considered

- **Also require cure to pay the current month's own not-yet-overdue
  installment**, fully "catching up" the account rather than just erasing
  the backlog. Rejected: `past_due_amount`/`dpd` already return to exactly
  0 under the chosen definition (both use the same `due_date < month_end`
  boundary), so this would only have changed the total cure *amount*, not
  whether the contract counts as delinquent - added complexity without
  changing the property this phase actually needed.
- **Track cure/relapse as explicit new columns on `contracts` or
  `account_monthly_snapshots`** (e.g. `times_cured`, `is_relapsed`).
  Rejected per section 3.2's own instruction: the information is fully
  derivable from existing events/snapshots, and an operational column that
  duplicates a derivable fact is exactly the kind of redundancy this
  project's contracts have consistently avoided (see
  `docs/adr/0009-dpd-sentinel-removal.md` for the same reasoning applied to
  the old `DPD=999` sentinel).
