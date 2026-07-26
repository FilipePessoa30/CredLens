-- Grain: one row per (suite_id, period) where period in
-- ('pre_shock', 'post_shock') - baseline vs. macroeconomic_stress
-- compared within each period, for the SAME suite (shared common random
-- numbers - see docs/common_random_numbers.md), never across suites.
--
-- shock_date is derived from the data itself, not hardcoded: the
-- macroeconomic_stress run's own fct_macro_monthly carries a
-- is_synthetic=true "synthetic_stress_index" row for every month the
-- shock is active (see docs/adr/0008-macro-context-provenance.md) -
-- min(reference_date) of those rows IS the shock date. Broadcast to
-- baseline via a same-suite join, since baseline itself carries no
-- synthetic rows of its own (macroeconomic_stress is the only scenario
-- that does).
--
-- Section 12.3's requirement this model exists to make checkable: the
-- PRE-shock period must show baseline and stress as identical (or
-- extremely close - see the model's own tolerance note below) on every
-- metric here, because the DGP is specifically designed so pre-shock
-- payment behavior is byte-identical between baseline and
-- macroeconomic_stress for the same seed - see
-- credlens.generation.payments._effective_payment_behavior. The
-- POST-shock period is where a real difference is expected. Never
-- compare pre-shock periods across different suites/seeds.
with shock_dates as (
    select run_id, min(reference_date) as shock_date
    from {{ ref('fct_macro_monthly') }}
    where is_synthetic
    group by 1
),
suite_shock_dates as (
    select r.suite_id, sd.shock_date
    from {{ ref('dim_run') }} r
    join shock_dates sd on r.run_id = sd.run_id
    where r.suite_id is not null
),
delinquency_with_period as (
    select
        d.suite_id,
        d.scenario,
        d.snapshot_date,
        case when d.snapshot_date < s.shock_date then 'pre_shock' else 'post_shock' end as period,
        d.total_balance,
        d.par90,
        d.rate_90plus
    from {{ ref('mart_delinquency_monthly') }} d
    join suite_shock_dates s on d.suite_id = s.suite_id
    where d.scenario in ('baseline', 'macroeconomic_stress')
),
writeoffs_with_period as (
    select
        r.suite_id,
        r.scenario,
        case when w.write_off_month < s.shock_date then 'pre_shock' else 'post_shock' end as period,
        w.write_off_count,
        w.total_write_off_amount
    from {{ ref('mart_writeoff_recovery') }} w
    join {{ ref('dim_run') }} r on w.run_id = r.run_id
    join suite_shock_dates s on r.suite_id = s.suite_id
    where r.scenario in ('baseline', 'macroeconomic_stress')
),
delinquency_agg as (
    select
        suite_id,
        scenario,
        period,
        count(distinct snapshot_date) as n_months_observed,
        avg(par90) as avg_par90,
        avg(rate_90plus) as avg_dpd90_contract_rate,
        avg(total_balance) as avg_outstanding_balance
    from delinquency_with_period
    group by 1, 2, 3
),
writeoffs_agg as (
    select
        suite_id,
        scenario,
        period,
        sum(write_off_count) as write_off_count,
        sum(total_write_off_amount) as write_off_amount
    from writeoffs_with_period
    group by 1, 2, 3
),
combined as (
    select
        d.suite_id,
        d.scenario,
        d.period,
        d.n_months_observed,
        d.avg_par90,
        d.avg_dpd90_contract_rate,
        d.avg_outstanding_balance,
        coalesce(w.write_off_count, 0) as write_off_count,
        coalesce(w.write_off_amount, 0) as write_off_amount
    from delinquency_agg d
    left join writeoffs_agg w
        on d.suite_id = w.suite_id and d.scenario = w.scenario and d.period = w.period
),
baseline as (
    select
        suite_id,
        period,
        n_months_observed as baseline_n_months,
        avg_par90 as baseline_par90,
        avg_dpd90_contract_rate as baseline_dpd90_rate,
        avg_outstanding_balance as baseline_outstanding_balance,
        write_off_count as baseline_write_off_count,
        write_off_amount as baseline_write_off_amount
    from combined
    where scenario = 'baseline'
),
stress as (
    select
        suite_id,
        period,
        n_months_observed as stress_n_months,
        avg_par90 as stress_par90,
        avg_dpd90_contract_rate as stress_dpd90_rate,
        avg_outstanding_balance as stress_outstanding_balance,
        write_off_count as stress_write_off_count,
        write_off_amount as stress_write_off_amount
    from combined
    where scenario = 'macroeconomic_stress'
)
select
    b.suite_id,
    b.period,
    sd.shock_date,
    b.baseline_n_months,
    s.stress_n_months,
    b.baseline_par90,
    s.stress_par90,
    (s.stress_par90 - b.baseline_par90) as par90_delta_abs,
    b.baseline_dpd90_rate,
    s.stress_dpd90_rate,
    (s.stress_dpd90_rate - b.baseline_dpd90_rate) as dpd90_rate_delta_abs,
    b.baseline_outstanding_balance,
    s.stress_outstanding_balance,
    b.baseline_write_off_count,
    s.stress_write_off_count,
    (s.stress_write_off_count - b.baseline_write_off_count) as write_off_count_delta_abs,
    b.baseline_write_off_amount,
    s.stress_write_off_amount
from baseline b
join stress s on b.suite_id = s.suite_id and b.period = s.period
join suite_shock_dates sd on b.suite_id = sd.suite_id
