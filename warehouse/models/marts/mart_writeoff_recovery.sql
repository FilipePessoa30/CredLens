-- Grain: one row per (run_id, write_off_month). Write-off/recovery KPIs.
select
    run_id,
    date_trunc('month', write_off_date) as write_off_month,
    count(*) as write_off_count,
    sum(write_off_amount) as total_write_off_amount,
    sum(case when has_recovery then 1 else 0 end) as recovery_count,
    sum(coalesce(recovery_amount, 0)) as total_recovery_amount,
    case when sum(write_off_amount) > 0
        then sum(coalesce(recovery_amount, 0)) / sum(write_off_amount)
    end as recovery_rate,
    avg(days_to_recovery) as avg_days_to_recovery
from {{ ref('int_write_off_recovery') }}
group by 1, 2
