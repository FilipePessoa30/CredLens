-- A month spine spanning every selected run's own simulated period
-- (generation_runs.period_start/period_end) - the anchor for "as of"
-- filters, vintage/MOB, and gap detection elsewhere in this layer.
with bounds as (
    select
        min(period_start) as min_date,
        max(period_end) as max_date
    from {{ ref('stg_generation_runs') }}
),
spine as (
    select unnest(
        generate_series(
            date_trunc('month', (select min_date from bounds)),
            date_trunc('month', (select max_date from bounds)),
            interval 1 month
        )
    ) as month_start
)
select
    cast(month_start as date) as month_start,
    cast(month_start + interval 1 month - interval 1 day as date) as month_end,
    cast(extract(year from month_start) as integer) as calendar_year,
    cast(extract(month from month_start) as integer) as calendar_month
from spine
