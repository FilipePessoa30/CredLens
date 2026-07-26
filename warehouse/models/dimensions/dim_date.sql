-- Grain: one row per calendar month. Natural key: month_start. No SCD
-- needed (a calendar month's own attributes never change).
select
    cast(strftime(month_start, '%Y%m') as integer) as date_key,
    month_start as month_date,
    month_end,
    calendar_year,
    calendar_month
from {{ ref('int_calendar_months') }}
