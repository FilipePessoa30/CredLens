select
    {{ surrogate_key(['run_id', 'application_id']) }} as application_key,
    run_id,
    application_id,
    {{ money('declared_income') }} as declared_income,
    cast(debt_to_income as double) as debt_to_income,
    cast(employment_months as double) as employment_months,
    cast(relationship_months as double) as relationship_months,
    bureau_score_bucket,
    {{ money('requested_amount') }} as requested_amount,
    cast(requested_term_months as integer) as requested_term_months,
    cast(feature_snapshot_at as timestamp) as feature_snapshot_at
from {{ ref('raw_application_features') }}
