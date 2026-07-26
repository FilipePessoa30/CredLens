-- Grain: one row per (run_id, snapshot_date, from_bucket, to_bucket).
-- Month-over-month DPD bucket TRANSITIONS for the SAME contract
-- (docs/warehouse_architecture.md "temporal semantics": roll rates only
-- ever compare a contract's own consecutive months, never different
-- contracts). "Roll forward" = to_bucket worse than from_bucket;
-- "roll back"/cure = to_bucket better; "stable" = unchanged.
select
    run_id,
    suite_id,
    scenario,
    seed,
    scale,
    snapshot_date,
    prior_month_dpd_bucket as from_bucket,
    dpd_bucket as to_bucket,
    count(*) as contract_count,
    sum(total_balance) as balance
from {{ ref('fct_account_monthly') }}
where prior_month_dpd_bucket is not null
group by 1, 2, 3, 4, 5, 6, 7, 8
