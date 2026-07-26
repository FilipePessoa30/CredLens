select
    {{ surrogate_key(['run_id', 'customer_id']) }} as customer_key,
    run_id,
    suite_id,
    scenario,
    seed,
    scale,
    customer_id,
    cast(created_at as timestamp) as created_at
from {{ ref('raw_customers') }}
