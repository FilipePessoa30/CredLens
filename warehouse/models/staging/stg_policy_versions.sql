select
    {{ surrogate_key(['run_id', 'policy_version_id']) }} as policy_version_key,
    run_id,
    scenario,
    policy_version_id,
    name as policy_name,
    cast(version as integer) as policy_version_number,
    cast(effective_from as timestamp) as effective_from,
    cast(effective_to as timestamp) as effective_to,
    status,
    rules_reference,
    change_reason
from {{ ref('raw_policy_versions') }}
