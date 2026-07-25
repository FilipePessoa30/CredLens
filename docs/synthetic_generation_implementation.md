# Synthetic Generation Implementation (Phase 4A)

This document describes what actually exists as of Phase 4A: a deterministic generator for the `baseline` scenario only. `docs/synthetic_generation_spec.md` remains the design-level specification (population/origination/performance/temporal-dependence, all 6 scenarios); this document is the as-built implementation record for the one scenario that is actually runnable.

**Everything this generator produces is synthetic.** No parameter here is claimed to represent a real lender, a real Brazilian credit market statistic, or a real applicant population - every numeric choice in `config/synthetic/baseline.generation.yaml` is an explicit, documented synthetic assumption (see `docs/assumptions_and_limitations.md`). Public context (BCB SGS series) is never used as an individual-level feature - see `docs/adr/0008-macro-context-provenance.md`. The generator is not a credit-granting model, and its output cannot be used to make or imply any real credit decision.

## Two configuration layers, deliberately kept separate

- `config/synthetic/scenarios/baseline.blueprint.yaml` - the narrative design document (5 sections, each parameter self-describing description/unit/justification/status). Read by `credlens synthetic scenarios`/`validate-blueprints`. As of Phase 4A its top-level `status` is `synthetic_assumptions_specified` (a new `BlueprintStatus` value, `src/credlens/synthetic.py`) - concrete synthetic values exist, but nothing here is calibrated from real data.
- `config/synthetic/baseline.generation.yaml` - the strongly-typed, Pydantic-validated (`src/credlens/generation/config.py`) configuration the generator code actually reads: scale presets, period, and every numeric knob (income ranges, approval cutoff, payment-behavior probabilities, write-off threshold, recovery parameters, tolerances, output paths).

Two files instead of one because they serve different readers: a human deciding what baseline should even contain, versus code that needs typed, validated values. Every value in the blueprint mirrors the executable config exactly - see the blueprint's own `justification` fields.

## Architecture

```text
src/credlens/generation/
├── config.py         # GenerationConfig (Pydantic) + Scale presets
├── rng.py             # RunRandomStreams: 12 independent SeedSequence-derived substreams
├── ids.py              # IdFactory: deterministic, sequential, prefixed, non-CPF ids
├── population.py      # customers
├── applications.py    # applications + application_features (frozen) + fairness_attributes
├── policies.py         # the single baseline policy_versions row
├── decisions.py        # synthetic decision score (never reads the truth layer) + credit_decisions
├── contracts.py        # booking: which approved applications become contracts
├── schedules.py        # Decimal-based reducing-balance amortization -> installments
├── allocations.py      # deterministic fees -> interest -> principal payment allocation
├── snapshots.py         # DPD/bucket/balance derivation from in-memory ledger state
├── collections.py      # collection_events decision + row construction
├── writeoffs.py         # write-off threshold decision + event row construction
├── recoveries.py        # recovery scheduling (decided once, at write-off time) + event row
├── payments.py          # simulate_portfolio_ledger: the month-by-month orchestrating loop
├── macro.py              # re-expresses real, already-acquired BCB data - never invents values
├── truth.py               # the synthetic-truth layer (latent payment propensity) - isolated
├── manifest.py            # canonical hashing (per-table, config, global) + manifest.json
├── writers.py             # Parquet output, path-safety, atomic staging -> promotion
├── validation.py          # contracts (strict) + PII safety + statistical checks
└── orchestrator.py        # generate_baseline(): ties every step together in causal order
```

## Events as the source of truth

`payments.py`'s `simulate_portfolio_ledger` is the only place account balances, DPD, and cumulative fields are computed. It never lets a probability draw set `account_monthly_snapshots.dpd`/`total_balance` directly - it mutates an in-memory ledger (`OpenInstallment` remaining principal/interest/fees per installment) via the same `allocate_payment` function real payment processing would use, and every snapshot field is *derived* from that ledger state (`snapshots.derive_snapshot_row`) at each month-end. The per-contract latent payment propensity (`truth.py`, physically isolated - see below) only ever influences *whether/how much* a contract pays in a given month; it never appears in, or determines, any operational table's value directly.

## Causal order

Matches `docs/temporal_semantics.md` exactly: customer → application → frozen features (+ fairness attributes) → decision → contract (booking) → installment schedule → month-by-month payment behavior → allocation → snapshot → collections/write-off/recovery, all within `orchestrator.generate_baseline`'s single top-to-bottom call sequence. Macro context is read independently (real BCB data, no dependency on the simulated portfolio) and merged in at the end.

## Reproducibility

- **RNG**: `rng.RunRandomStreams` derives 12 independent `numpy.random.Generator` instances from one `SeedSequence(seed).spawn(12)` call, in a fixed declared order (`STREAM_NAMES`). Consuming one stream never shifts another (verified in `tests/test_generation_rng_ids.py`).
- **IDs**: `ids.IdFactory` issues sequential, zero-padded, prefixed ids (`CUS_<hash>_0000001`, never `uuid4()`, never CPF-shaped - checked by the same `check_no_document_like_identifiers` every contract already runs).
- **`generation_run_id`**: a deterministic function of `(scenario, scale, seed, config_hash)` - the same inputs always produce the same run id, which is what makes `--force` meaningful (re-running with identical inputs targets the same directory).
- **Canonical hashing** (`manifest.py`): each table is hashed with columns sorted alphabetically, rows sorted by their own canonical string representation (order-independent), nulls mapped to a fixed sentinel, floats rendered with `repr()`. This does not promise byte-identical Parquet files across pandas/pyarrow versions - only that the same logical content hashes the same.
- **`generation_runs` is excluded from the reproducibility hash.** It records `generated_at`, a wall-clock timestamp that legitimately differs between two otherwise-identical invocations - including it would make "same seed → same hash" true for the *portfolio* but false for the *run metadata*, for no useful reason. It is still written to disk on every run.

## A real bug the reproducibility proof itself caught

Building the "same seed → same hash" test (`tests/test_generation_orchestrator.py`) surfaced a genuine bug: a payment made on the last day of a month, reversed the next calendar day, could have its reversal land in the *following* month. The generator's in-memory ledger nets the reversal out immediately regardless of date; the independent, output-side reconciliation (`credlens.contracts.financial_rules`) sums events strictly by each one's own `settlement_date`. A cross-month reversal made those two views disagree - `SNAPSHOT_CUMULATIVE_PAID_MISMATCH`/`SNAPSHOT_BALANCE_RECONCILIATION_FAILED` on the affected contract's month-end snapshot. Fixed by constraining a reversal to settle within the same calendar month as its original payment (`payments.py`); a reversal that would cross a month boundary is simply not applied that time. See `tests/test_generation_orchestrator.py::TestDeterministicContentHash` and `tests/test_generation_ledger_integration.py` for the regression coverage.

## Other real bugs found during this phase's construction

- **`ALLOCATION_EXCEEDS_PAYMENT` false positive**: the Phase 3 rule compared `allocated == payment.amount` with a strict `>` and no tolerance; summing several already-rounded float64 components could exceed the payment by a fraction of a cent. Fixed by adding the same `0.01` tolerance every other reconciliation rule already uses (`credlens/contracts/relational_rules.py`).
- **Empty-result tables losing their schema**: `pd.DataFrame([])` (zero recovery events, for example) has zero columns, which broke both Parquet writing and contract column checks. Fixed with an explicit column list per output table (`payments._frame`).
- **`pd.merge_asof` dtype mismatch on all-empty inputs**: an empty `payments`/`payment_allocations` pair made pandas infer `float64` for `installment_id`, which doesn't match the real string ids on the other side of the merge. Fixed with an explicit `.astype(str)` before the merge (`financial_rules._ledger_reconciliation`).
- **Missing `due_date < snapshot_date` filter**: the first version of the ledger reconciliation's DPD formula considered *any* open installment, including ones not yet due, producing negative "days overdue." Fixed by adding the filter the formula was always supposed to have (`financial_rules._ledger_reconciliation`) - caught by hand-verifying the rebuilt `valid_minimal_scenario` fixture against the formula before trusting either.
- **`credlens synthetic validate` silently skipping tables**: an early version filtered to contracts classified `synthetic_operational`, which incidentally excluded `fairness_attributes` (`evaluation_only`) and `macro_context_monthly` (`public_market_context` as of this phase's own fix) - both real tables in every run. Fixed by validating every contract defined under `contracts/operational/`, regardless of its classification.

## Financial precision

Amortization (`schedules.py`) uses Python's `Decimal`, quantized to 2 decimal places with `ROUND_HALF_UP` every period; any residual cent from rounding is absorbed into the *last* installment, so the sum of scheduled principal reconciles exactly to `financed_amount`. This is a standard reducing-balance (Price/French) schedule - a CredLens convention choice, not a claim that it's the only valid method.

## Statistical validation is not a business finding

`validation.run_statistical_checks` verifies technical properties of the generator's own output (approval rate is within [0,100]%, booking rate never exceeds approval rate, both performing and non-performing installments exist, DPD is never negative, and so on). These are sanity checks on the generator's *mechanics* - never a claim about real-world approval rates, default rates, or any other business quantity. They do not, by themselves, fail a run whose contracts and PII checks are otherwise clean (`GenerationValidationOutcome.passed` only requires `contracts_passed and pii_safe`) - see `docs/adr/0006-audit-vs-strict-validation.md` for the same audit/strict distinction this mirrors.

## Validation and atomicity

Every run is written entirely to a private staging directory under `data/synthetic/.staging/` first, validated (contracts strict mode, PII safety, statistical checks), and only **promoted** (an atomic `os.replace`) into `data/synthetic/<generation_run_id>/` if validation passes. A failed run's diagnostic artifacts (including `contract_validation.json`, the full per-contract findings) stay in staging rather than being presented as a valid result - `credlens synthetic generate` exits 1 and prints that the run failed. `data/synthetic_truth/<generation_run_id>/` is staged and promoted the same way, independently.

## Output layout

```text
data/synthetic/<generation_run_id>/
├── operational/*.parquet      # the 16 operational tables
├── manifest.json               # seed, config_hash, per-table + global canonical hashes, timing
├── config_snapshot.yaml        # the exact resolved GenerationConfig used
├── contract_validation.json    # full per-contract findings
└── generation_summary.json     # pass/fail summary, statistical check results

data/synthetic_truth/<generation_run_id>/
├── latent_customer_truth.parquet   # customer_id -> latent_payment_propensity
├── latent_contract_truth.parquet   # contract_id -> latent_payment_propensity
└── truth_manifest.json
```

Both directories are git-ignored (`data/*` already covers them - see `.gitignore` and `data/README.md`).

## Synthetic-truth isolation

Per `docs/adr/0007-synthetic-truth-isolation.md`: the latent payment propensity (`truth.py`) is written *only* to `data/synthetic_truth/`, never merged into any operational table, never read by `decisions.compute_decision_score` (which only reads `application_features` - the visible, frozen-at-proposal data a real policy could see). No CLI command in this phase reads the truth directory at all - it exists solely for a future generator-validation pass. `tests/test_generation_events_and_context.py::TestTruthLayer` pins this structurally (the truth table's own columns never collide with `customers.yaml`'s declared columns).

## Scale presets

| Scale | Customers (config) | Purpose | Run automatically in tests/CI? |
|---|---:|---|---|
| `smoke` | 200 | Fast, deterministic sanity check - covers every state (approve/reject/pay/delinquent/cure/write-off/recover) in well under a second. | Yes - `pytest` runs several real smoke-scale generations. |
| `sample` | 5,000 | Development/demo depth. | No - exercised manually once for this phase's validation (~57s, see the final report's performance table); not part of the automated test suite to keep `pytest` fast. |
| `portfolio` | 50,000 | Demonstration scale. | No - not executed in this phase at all, per this phase's explicit scope. |

## What is explicitly not built in Phase 4A

- Every scenario except `baseline` (`policy_expansion`, `policy_tightening`, `macroeconomic_stress`, `collections_change`, `data_quality_incident`) - `credlens synthetic generate --scenario <other>` raises `ScenarioNotCalibratedError` before any generation runs.
- The `macroeconomic_stress` scenario's synthetic macro shocks - `macro.py` only ever produces `source_type=public_bcb_observation` rows in this phase; `synthetic_shock`/`derived_index` rows are schema-ready (`docs/adr/0008`) but never emitted.
- A warehouse, SQL analytics, a risk model, or a dashboard - none of these read the generator's output in this phase.
