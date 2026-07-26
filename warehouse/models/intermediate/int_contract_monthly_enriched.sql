-- The backbone of every delinquency/vintage/cure/relapse mart: one row
-- per (contract, snapshot_date) - a STOCK snapshot (docs/warehouse_architecture.md
-- "flow vs. stock") - enriched with vintage/MOB and, via window functions
-- over each contract's own snapshot history, cure and relapse flags.
--
-- Cure/relapse semantics (docs/adr/0010-cure-semantics-and-relapse.md):
--   is_cure_month:    this month's status is 'active' and last month's was
--                      'delinquent' - the account just eliminated its
--                      overdue amount without the contract terminating.
--   is_relapse_month: this month's status is 'delinquent', last month's was
--                      NOT already 'delinquent' (so this is the first
--                      month of a NEW delinquency episode, not a
--                      continuation), AND at least one is_cure_month
--                      happened at some earlier point in this same
--                      contract's history. Both conditions matter: without
--                      the "first month of a new episode" guard, every
--                      month of a multi-month delinquent stretch after a
--                      cure would be double-counted as its own relapse.
with base as (
    select
        s.contract_key,
        s.run_id,
        s.suite_id,
        s.scenario,
        s.seed,
        s.scale,
        s.contract_id,
        s.snapshot_date,
        s.dpd,
        s.dpd_bucket,
        s.contract_status,
        s.outstanding_principal,
        s.outstanding_interest,
        s.outstanding_fees,
        s.total_balance,
        s.past_due_amount,
        s.exposure,
        s.cumulative_paid,
        s.cumulative_write_off,
        c.customer_key,
        c.financed_amount,
        date_trunc('month', c.disbursement_date) as vintage_month
    from {{ ref('stg_account_monthly_snapshots') }} s
    join {{ ref('stg_contracts') }} c on s.contract_key = c.contract_key
),
with_history as (
    select
        *,
        cast(
            datediff('month', vintage_month, date_trunc('month', snapshot_date)) as integer
        ) as months_on_book,
        lag(contract_status) over (
            partition by contract_key order by snapshot_date
        ) as prior_month_status,
        lag(dpd_bucket) over (
            partition by contract_key order by snapshot_date
        ) as prior_month_dpd_bucket
    from base
),
with_cure as (
    select
        *,
        (contract_status = 'active' and prior_month_status = 'delinquent') as is_cure_month
    from with_history
),
with_relapse as (
    select
        *,
        (
            contract_status = 'delinquent'
            and coalesce(prior_month_status, '') != 'delinquent'
            and sum(case when is_cure_month then 1 else 0 end) over (
                partition by contract_key
                order by snapshot_date
                rows between unbounded preceding and 1 preceding
            ) > 0
        ) as is_relapse_month
    from with_cure
)
select * from with_relapse
