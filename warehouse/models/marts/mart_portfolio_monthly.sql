-- Grain: one row per (run_id, snapshot_date). Portfolio STOCK KPIs
-- (outstanding balance, active contracts, average ticket) plus that
-- month's FLOW payment-behavior counts (partial payments, prepayments).
with stock as (
    select
        run_id,
        suite_id,
        scenario,
        seed,
        scale,
        snapshot_date,
        count(*) as total_contracts,
        sum(case when contract_status in ('active', 'delinquent') then 1 else 0 end) as active_contracts,
        sum(total_balance) as outstanding_balance,
        sum(cumulative_paid) as cumulative_paid_total,
        avg(financed_amount) as avg_ticket
    from {{ ref('fct_account_monthly') }}
    group by 1, 2, 3, 4, 5, 6
),
flow as (
    select
        run_id,
        payment_month,
        sum(case when payment_type = 'partial' and not is_reversal then 1 else 0 end) as partial_payment_count,
        sum(case when payment_type = 'prepayment' and not is_reversal then 1 else 0 end) as prepayment_count
    from {{ ref('fct_payments') }}
    group by 1, 2
)
select
    s.*,
    coalesce(f.partial_payment_count, 0) as partial_payment_count,
    coalesce(f.prepayment_count, 0) as prepayment_count
from stock s
left join flow f
    on s.run_id = f.run_id
    and date_trunc('month', s.snapshot_date) = f.payment_month
