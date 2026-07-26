-- Grain: one row per (run_id, vintage_month, months_on_book). Vintage
-- (origination-cohort) analysis - incidence of delinquency and
-- cumulative write-off BY MOB, not by calendar date, so cohorts of
-- different ages can be compared on a like-for-like maturity basis.
-- LIMITATION (see docs/warehouse_architecture.md): more recent vintages
-- have fewer MOB periods observed within the simulated period - never
-- compare two cohorts beyond the MOB range BOTH actually reached
-- (max_mob_observed_for_cohort, provided below, makes this checkable).
with cohort_month as (
    select
        run_id,
        vintage_month,
        max(months_on_book) as max_mob_observed_for_cohort
    from {{ ref('fct_account_monthly') }}
    group by 1, 2
)
select
    a.run_id,
    a.suite_id,
    a.scenario,
    a.seed,
    a.scale,
    a.vintage_month,
    a.months_on_book,
    c.max_mob_observed_for_cohort,
    count(distinct a.contract_key) as contracts_observed,
    sum(a.total_balance) as total_balance,
    sum(a.financed_amount) as total_financed_amount,
    sum(case when a.dpd_bucket in ('30-59', '60-89', '90+') then 1 else 0 end) as contracts_30plus,
    sum(case when a.dpd_bucket in ('60-89', '90+') then 1 else 0 end) as contracts_60plus,
    sum(case when a.dpd_bucket = '90+' then 1 else 0 end) as contracts_90plus,
    sum(a.cumulative_write_off) as cumulative_write_off
from {{ ref('fct_account_monthly') }} a
join cohort_month c on a.run_id = c.run_id and a.vintage_month = c.vintage_month
group by 1, 2, 3, 4, 5, 6, 7, 8
