select
    {{ surrogate_key(['run_id', 'decision_id']) }} as decision_key,
    {{ surrogate_key(['run_id', 'application_id']) }} as application_key,
    {{ surrogate_key(['run_id', 'policy_version_id']) }} as policy_version_key,
    run_id,
    decision_id,
    application_id,
    policy_version_id,
    cast(decision_timestamp as timestamp) as decision_timestamp,
    outcome,
    reason_code,
    {{ money('approved_amount') }} as approved_amount,
    cast(approved_term_months as integer) as approved_term_months,
    cast(offered_rate as double) as offered_rate,
    cast(is_final as boolean) as is_final,
    logic_version
from {{ ref('raw_credit_decisions') }}
