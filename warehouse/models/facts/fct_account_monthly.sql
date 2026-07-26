-- Grain: one row per (contract, snapshot_date). STOCK snapshot (a
-- point-in-time balance sheet position), NOT a flow - never sum
-- total_balance/exposure ACROSS months for the same contract (that would
-- double-count outstanding principal that simply carried over). Safe to
-- sum total_balance/exposure ACROSS CONTRACTS within the same
-- snapshot_date (a portfolio-level balance at one point in time). FK:
-- contract_key -> fct_contracts, dpd_bucket -> dim_dpd_bucket.
-- is_cure_month/is_relapse_month (Phase 5) come from
-- int_contract_monthly_enriched's window-function derivation - see
-- docs/adr/0010-cure-semantics-and-relapse.md.
select
    contract_key,
    customer_key,
    run_id,
    suite_id,
    scenario,
    seed,
    scale,
    contract_id,
    snapshot_date,
    vintage_month,
    months_on_book,
    dpd,
    dpd_bucket,
    prior_month_dpd_bucket,
    contract_status,
    prior_month_status,
    outstanding_principal,
    outstanding_interest,
    outstanding_fees,
    total_balance,
    past_due_amount,
    exposure,
    cumulative_paid,
    cumulative_write_off,
    financed_amount,
    is_cure_month,
    is_relapse_month
from {{ ref('int_contract_monthly_enriched') }}
