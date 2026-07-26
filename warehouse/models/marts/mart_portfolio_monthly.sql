-- Grain: one row per (run_id, snapshot_date). Portfolio STOCK KPIs
-- (outstanding balance, active contracts, average ticket, overdue
-- scheduled amount) plus that month's own FLOW figures: payment-behavior
-- counts (partial payments, prepayments), the schedule's own DUE amount
-- for THIS calendar month only (never the whole future schedule - see
-- warehouse/kpi_catalog.yml POR-003's own grain note), and what was
-- actually paid this same month, so paid_to_scheduled_ratio compares two
-- numbers from the SAME period.
--
-- scheduled vs. due vs. overdue (Phase 6 section 7.1's required
-- distinction): "scheduled" = what the original amortization schedule
-- says an installment amounts to, in total, regardless of when it is
-- due - see fct_installments.scheduled_total. "Due this month" =
-- scheduled installments whose due_date falls within snapshot_date's own
-- calendar month - this mart's scheduled_amount_due_this_month. "Overdue"
-- = due_date already in the past AND still not fully paid as of
-- snapshot_date - fct_account_monthly.past_due_amount, surfaced here as
-- overdue_scheduled_amount. A prepayment settles future not-yet-due
-- installments early; those installments' scheduled_total is NOT removed
-- from a past month's scheduled_amount_due_this_month (that figure is
-- fixed at schedule-creation time, not revised after the fact) - only
-- outstanding_balance and overdue_scheduled_amount (both STOCK, read as
-- of snapshot_date) reflect the early payoff. A write-off does not alter
-- scheduled_amount_due_this_month for months already reported; it stops
-- future accrual, visible as outstanding_balance going to 0 and no
-- further overdue amount accruing in later snapshots.
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
        sum(past_due_amount) as overdue_scheduled_amount,
        avg(financed_amount) as avg_ticket
    from {{ ref('fct_account_monthly') }}
    group by 1, 2, 3, 4, 5, 6
),
payment_flow as (
    select
        run_id,
        payment_month,
        sum(case when payment_type = 'partial' and not is_reversal then 1 else 0 end) as partial_payment_count,
        sum(case when payment_type = 'prepayment' and not is_reversal then 1 else 0 end) as prepayment_count,
        sum(net_amount) as paid_amount_this_month
    from {{ ref('fct_payments') }}
    group by 1, 2
),
scheduled_flow as (
    -- "Due this month" only - due_date's own calendar month, never a
    -- lifetime total. installment_status/write-off state is NOT filtered
    -- here on purpose: the schedule's due amount for a given month is a
    -- fact about the ORIGINAL amortization plan, fixed when the contract
    -- was booked - see this model's own header note.
    select
        i.run_id,
        date_trunc('month', i.due_date) as due_month,
        sum(i.scheduled_total) as scheduled_amount_due_this_month,
        sum(i.scheduled_principal) as scheduled_principal_due_this_month,
        sum(i.scheduled_interest) as scheduled_interest_due_this_month,
        sum(i.scheduled_fees) as scheduled_fees_due_this_month
    from {{ ref('fct_installments') }} i
    group by 1, 2
)
select
    s.*,
    coalesce(pf.partial_payment_count, 0) as partial_payment_count,
    coalesce(pf.prepayment_count, 0) as prepayment_count,
    coalesce(pf.paid_amount_this_month, 0) as paid_amount_this_month,
    coalesce(sf.scheduled_amount_due_this_month, 0) as scheduled_amount_due_this_month,
    coalesce(sf.scheduled_principal_due_this_month, 0) as scheduled_principal_due_this_month,
    coalesce(sf.scheduled_interest_due_this_month, 0) as scheduled_interest_due_this_month,
    coalesce(sf.scheduled_fees_due_this_month, 0) as scheduled_fees_due_this_month,
    case when coalesce(sf.scheduled_amount_due_this_month, 0) > 0
        then coalesce(pf.paid_amount_this_month, 0) / sf.scheduled_amount_due_this_month
    end as paid_to_scheduled_ratio
from stock s
left join payment_flow pf
    on s.run_id = pf.run_id
    and date_trunc('month', s.snapshot_date) = pf.payment_month
left join scheduled_flow sf
    on s.run_id = sf.run_id
    and date_trunc('month', s.snapshot_date) = sf.due_month
