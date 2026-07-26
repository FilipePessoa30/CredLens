-- Grain: one row per (suite_id, scenario) where scenario != 'baseline'.
-- Baseline vs. scenario, side by side, absolute and relative deltas.
-- EVERY number here is a fact about this synthetic DGP's own
-- construction, never a claim about a real institution - see
-- docs/counterfactual_scenarios.md. dpd90_rate is read at each run's OWN
-- final observed month (not necessarily the same calendar date across
-- runs of different scale, though within one suite all runs share the
-- same period).
with run_approval as (
    select
        d.run_id,
        sum(case when d.outcome = 'approved' then 1 else 0 end)::double
            / nullif(count(*), 0) as approval_rate
    from {{ ref('fct_credit_decisions') }} d
    group by 1
),
run_final_month as (
    select run_id, max(snapshot_date) as final_snapshot_date
    from {{ ref('fct_account_monthly') }}
    group by 1
),
run_dpd90 as (
    select
        a.run_id,
        sum(case when a.dpd_bucket = '90+' then 1 else 0 end)::double
            / nullif(count(*), 0) as dpd90_rate_final_month
    from {{ ref('fct_account_monthly') }} a
    join run_final_month f
        on a.run_id = f.run_id and a.snapshot_date = f.final_snapshot_date
    group by 1
),
run_write_offs as (
    select run_id, count(*) as write_off_count
    from {{ ref('fct_writeoffs') }}
    group by 1
),
run_level as (
    select
        r.run_id,
        r.suite_id,
        r.scenario,
        coalesce(ra.approval_rate, 0) as approval_rate,
        coalesce(rd.dpd90_rate_final_month, 0) as dpd90_rate_final_month,
        coalesce(rw.write_off_count, 0) as write_off_count
    from {{ ref('dim_run') }} r
    left join run_approval ra on r.run_id = ra.run_id
    left join run_dpd90 rd on r.run_id = rd.run_id
    left join run_write_offs rw on r.run_id = rw.run_id
    where r.suite_id is not null
),
baseline as (
    select
        suite_id,
        approval_rate as baseline_approval_rate,
        dpd90_rate_final_month as baseline_dpd90_rate,
        write_off_count as baseline_write_off_count
    from run_level
    where scenario = 'baseline'
)
select
    rl.suite_id,
    rl.scenario,
    rl.run_id,
    rl.approval_rate,
    b.baseline_approval_rate,
    rl.approval_rate - b.baseline_approval_rate as approval_rate_delta_abs,
    case when b.baseline_approval_rate > 0
        then (rl.approval_rate - b.baseline_approval_rate) / b.baseline_approval_rate
    end as approval_rate_delta_rel,
    rl.dpd90_rate_final_month,
    b.baseline_dpd90_rate,
    rl.dpd90_rate_final_month - b.baseline_dpd90_rate as dpd90_rate_delta_abs,
    rl.write_off_count,
    b.baseline_write_off_count,
    rl.write_off_count - b.baseline_write_off_count as write_off_count_delta_abs
from run_level rl
join baseline b on rl.suite_id = b.suite_id
where rl.scenario != 'baseline'
