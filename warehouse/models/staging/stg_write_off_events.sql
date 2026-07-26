select
    {{ surrogate_key(['run_id', 'write_off_id']) }} as write_off_key,
    {{ surrogate_key(['run_id', 'contract_id']) }} as contract_key,
    run_id,
    suite_id,
    scenario,
    seed,
    scale,
    write_off_id,
    contract_id,
    cast(write_off_date as date) as write_off_date,
    {{ money('amount') }} as amount,
    {{ money('principal') }} as principal,
    {{ money('interest') }} as interest,
    {{ money('fees') }} as fees,
    reason,
    policy_reference
from {{ ref('raw_write_off_events') }}
