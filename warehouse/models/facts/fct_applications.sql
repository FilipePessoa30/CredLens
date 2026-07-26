-- Grain: one row per application. FLOW event (an application was
-- submitted). FK: customer_key -> dim_customer, channel -> dim_channel,
-- run_id -> dim_run. Additive measure: requested_amount (one submission,
-- one amount - safe to sum "total requested" within a run/period).
select
    application_key,
    customer_key,
    run_id,
    application_id,
    submitted_at,
    date_trunc('month', submitted_at) as submitted_month,
    channel,
    product,
    requested_amount,
    requested_term_months,
    status as application_status
from {{ ref('stg_applications') }}
