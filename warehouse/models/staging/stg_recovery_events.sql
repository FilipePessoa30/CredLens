select
    {{ surrogate_key(['run_id', 'recovery_id']) }} as recovery_key,
    {{ surrogate_key(['run_id', 'contract_id']) }} as contract_key,
    {{ surrogate_key(['run_id', 'write_off_id']) }} as write_off_key,
    run_id,
    suite_id,
    scenario,
    seed,
    scale,
    recovery_id,
    contract_id,
    write_off_id,
    cast(recovery_date as date) as recovery_date,
    {{ money('amount') }} as amount,
    channel,
    source
from {{ ref('raw_recovery_events') }}
