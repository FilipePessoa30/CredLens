select
    {{ surrogate_key(['run_id', 'source_type', 'source_id', 'reference_date']) }} as macro_key,
    run_id,
    scenario,
    source_type,
    source_id,
    cast(series_code as integer) as series_code,
    cast(reference_date as date) as reference_date,
    cast(value as double) as value,
    unit,
    cast(is_synthetic as boolean) as is_synthetic,
    cast(retrieved_at as timestamp) as retrieved_at
from {{ ref('raw_macro_context_monthly') }}
