select
    {{ surrogate_key(['run_id', 'application_id']) }} as application_key,
    {{ surrogate_key(['run_id', 'customer_id']) }} as customer_key,
    run_id,
    suite_id,
    scenario,
    seed,
    scale,
    application_id,
    customer_id,
    cast(submitted_at as timestamp) as submitted_at,
    product,
    channel,
    {{ money('requested_amount') }} as requested_amount,
    cast(requested_term_months as integer) as requested_term_months,
    status
from {{ ref('raw_applications') }}
