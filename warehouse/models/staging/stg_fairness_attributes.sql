select
    {{ surrogate_key(['run_id', 'application_id']) }} as application_key,
    run_id,
    application_id,
    age_bracket,
    synthetic_gender,
    region
from {{ ref('raw_fairness_attributes') }}
