# Data Contracts

`credlens.contracts` (`src/credlens/contracts/`) is the machine-checked description of what every table - the four Phase 2 public sources and the sixteen tables of the not-yet-built synthetic operational layer - is supposed to look like. This document explains how it works and the decisions behind it. For the rule catalog itself, see `docs/business_rules.md`; for the contract file format, see `contracts/README.md`.

## Two things that look similar but are different

1. **Contract *metadata*** - the YAML files in `contracts/raw/` and `contracts/operational/`, describing columns, types, domains, keys, and rules. There are ~20 of these, loaded once per CLI invocation.
2. **Table *data*** - the actual rows in a CSV/JSON file (real, for the 4 raw sources; small artificial fixtures, for the 16 operational tables - nothing operational has been generated yet).

These are validated with **deliberately different techniques**, and mixing them up is the single most common way a validation framework becomes either unreadable or too slow to use on real data:

- **Metadata is validated with Pydantic** (`src/credlens/contracts/models.py`). It's a one-time, small-N structural parse (loading ~20 files), and the YAML shape is genuinely complex (nested columns, domains, foreign keys, business-rule references) - Pydantic gives typed parsing and precise error messages for a fraction of the hand-written validation code the Phase 1/2 dataclass pattern (`credlens.config`, `credlens.data.registry`) would need here. See `docs/adr/0006-audit-vs-strict-validation.md` for the fuller reasoning, including why Phase 1/2 deliberately avoided this same dependency at the time.
- **Table data is validated with vectorized pandas** (`domain_rules.py`, `relational_rules.py`, `temporal_rules.py`, `financial_rules.py`). Every check operates on a whole column/table at once (`.isin()`, `.duplicated()`, `pd.cut()`, boolean masks) - never a Python loop constructing one validator object per row. This is what makes `credlens contracts validate --contract uci_default_credit ...` run in well under a second against all 30,000 real rows, and is exactly as fast on a 3-row fixture. A row-by-row Pydantic-model-per-record approach was considered and rejected for this reason (see the "why not row-level Pydantic" note below).

### Why not row-level Pydantic for table data too?

It was considered. Two reasons against: performance (instantiating one validated model per row is measurably slower than a vectorized column operation at real dataset sizes, and this project explicitly targets not "validating millions of rows individually with OO models" per this phase's brief), and shape (several rules here are inherently cross-row or cross-table - e.g. "at most one final decision per application" or "allocations for a payment don't exceed it" - which a per-row model can't express at all; they need a groupby/join, which is what pandas is for.

## The two validation modes

| | `audit` | `strict` |
|---|---|---|
| Used for | `contracts/raw/*` (already-acquired public data) | `contracts/operational/*` and its test fixtures |
| Modifies data? | Never | Never |
| Missing required column | error | error |
| Unexpected column | warning (or error if the contract sets `strict_unexpected_columns: true`) | always error |
| Command exit code | Always 0 (diagnostic - matches `credlens data audit`'s Phase 2 behavior) | 1 if any `error`-severity finding exists |

Both modes run the exact same checks (`domain_rules.check_all` + every declared `business_rules[]`) - the only difference is what the CLI *does* with the result. This was a deliberate simplification over having two different rule sets: a rule is a rule regardless of mode; what changes is whether violating it blocks anything. See `docs/adr/0006-audit-vs-strict-validation.md`.

## Single-file vs. scenario-directory validation

`credlens contracts validate --contract X --path Y` accepts either:

- **A file**: only checks that need `X`'s own table run. Any business rule needing another table (e.g. `contract_after_decision` needing both `credit_decisions` and `contracts`) reports an `info`-severity "not evaluated" finding instead of crashing - visible, not silent.
- **A directory** (a "scenario"): every contract's file present in it, named `<contract_name>.<format>`, is loaded, so cross-table rules run too. This is how every fixture in `tests/fixtures/contracts/` works - each is a small directory with only the 1-3 files a specific rule actually needs, not all sixteen tables.

## Real bugs this system caught during its own construction

Not hypothetical - three genuine defects were found and fixed while building and testing this phase, each with a regression test:

1. **UCI `EDUCATION`/`MARRIAGE` undocumented codes** (Phase 2 debt, now automated) - `contracts/raw/uci_default_credit.yaml` encodes UCI's own documented domains; running `credlens contracts validate --contract uci_default_credit --path data/raw/... --mode audit` against the real 30,000-row file reproduces the exact finding (345 `EDUCATION` violations, 54 `MARRIAGE` violations) that Phase 2 found manually. See `docs/data_quality_audit.md`.
2. **A timezone comparison crash** - the first version of `approval_requires_valid_policy` crashed with `TypeError: Cannot compare tz-naive and tz-aware datetime-like objects` whenever a compared timestamp column was entirely empty (pandas infers a timezone-naive dtype for an all-`NaT` column, which then can't be compared to a timezone-aware one). Fixed by parsing every timestamp column with `pd.to_datetime(..., utc=True)` uniformly across `relational_rules.py` and `temporal_rules.py`. Caught by this phase's own `valid_minimal_scenario` fixture, not by a pre-written test.
3. **A type-mismatch false positive** - `macro_context_monthly.series_code` was first declared as a string domain (`in_set: ["20570", "21112"]`), but pandas reads that CSV column as `int64`, so every row failed domain validation. Fixed by declaring the column `type: integer` with an integer domain, matching how the data is actually typed once read. Caught by running the valid fixture through strict mode and seeing an unexpected failure.
4. **A missing check entirely** - the first version of this system validated schema/domain/PK/uniqueness but never actually checked `foreign_keys[]` against real data (only that the *contract* referenced a real other contract, not that individual *values* existed in it). Added `domain_rules.check_foreign_keys`, exercised by the `invalid_fk_orphan` fixture.
5. **`ALLOCATION_EXCEEDS_PAYMENT` false positive** (Phase 4A) - `payment_allocation_not_exceed_payment` compared `allocated == amount` with a strict `>` and no tolerance; the first real generator run produced a payment whose allocations summed to a few units of float64 epsilon *above* the payment amount, purely from adding several already-rounded components. Fixed by adding the same `0.01` tolerance every other reconciliation rule already used. Caught by validating real generated output, not a hand-written fixture.
6. **A cross-month reversal breaking reproducibility** (Phase 4A) - the generator's in-memory ledger netted a payment reversal out immediately regardless of calendar date; the independent, output-side reconciliation sums events strictly by `settlement_date`. A reversal dated into the month *after* its original payment made the two views disagree on that month's `cumulative_paid`/`total_balance`. Fixed by constraining a reversal to settle within the same month as its original payment. Caught by the "same seed → same content hash" determinism test failing unpredictably. See `docs/synthetic_generation_implementation.md`.
7. **`next_due_date`'s inclusive-boundary quirk almost got silently changed** (Phase 4B) - a performance optimization (pruning permanently-exhausted installments from the per-month scan) would have changed `account_monthly_snapshots.next_due_date` for same-day payoffs, since that one field's computation is deliberately inclusive of the snapshot date itself and doesn't filter by remaining balance. Caught by diffing every cell of a real `sample`-scale run against the pre-optimization output, not by code review. See `docs/performance_optimization.md`.

## Contract version changes since Phase 4A

`generation_runs` moved from version 2 to version 3 in Phase 4B: its `scenario` domain gained `contract_coverage`, its `status` domain gained `quarantined_expected_failure` (see `docs/data_quality_incident.md`), and it gained two new nullable columns, `suite_id` and `parent_run_id`, for counterfactual suites (see `docs/common_random_numbers.md`). No other operational contract changed version this phase - Phase 4B's new scenarios and the quarantine flow reuse the existing contract/business-rule set unchanged.

## What this system deliberately does not do

- It generates data for `baseline`, `policy_expansion`, `policy_tightening`, `macroeconomic_stress`, `collections_change`, and the `contract_coverage` test fixture as of Phase 4B - see `docs/synthetic_generation_implementation.md` and `docs/counterfactual_scenarios.md` for what's actually implemented, and `docs/synthetic_generation_spec.md` for the full six-scenario design. `data_quality_incident` remains without an executable generation config.
- It does not enforce full state-machine transition history (see `docs/state_machines.md`'s explicit gap statement).
- It does not evaluate arbitrary code from a contract YAML - `eval()` is never called anywhere in `src/credlens/contracts/`; domain rules are a closed, Pydantic-validated vocabulary (`in_set`/`min`/`max`/`regex`) and business rules are references to named, reviewed, tested Python functions (`registry.KNOWN_BUSINESS_RULE_CODES`), not inline expressions.
