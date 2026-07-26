-- Grain: one row per (run_id, submitted_month, channel). Funnel KPIs:
-- applications submitted -> decisioned -> approved -> booked. See
-- warehouse/kpi_catalog.yml "funnel" section for the exact formulas.
with base as (
    select * from {{ ref('int_applications_decisions_contracts') }}
),
monthly as (
    select
        run_id,
        suite_id,
        scenario,
        seed,
        scale,
        date_trunc('month', submitted_at) as submitted_month,
        channel,
        count(*) as applications_submitted,
        sum(case when was_decided then 1 else 0 end) as decisioned_applications,
        sum(case when is_approved then 1 else 0 end) as approved_count,
        sum(case when was_decided and not is_approved then 1 else 0 end) as rejected_count,
        sum(case when is_booked then 1 else 0 end) as booked_count,
        sum(case when is_booked then financed_amount else 0 end) as total_booked_amount
    from base
    group by 1, 2, 3, 4, 5, 6, 7
)
select
    *,
    case when decisioned_applications > 0
        then approved_count::double / decisioned_applications end as approval_rate,
    case when decisioned_applications > 0
        then rejected_count::double / decisioned_applications end as rejection_rate,
    case when approved_count > 0
        then booked_count::double / approved_count end as booking_rate_of_approved,
    case when applications_submitted > 0
        then booked_count::double / applications_submitted end as booking_rate_of_submitted,
    case when booked_count > 0
        then total_booked_amount / booked_count end as avg_booked_amount
from monthly
