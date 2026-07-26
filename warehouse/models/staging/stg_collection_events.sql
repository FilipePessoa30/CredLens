select
    {{ surrogate_key(['run_id', 'collection_event_id']) }} as collection_event_key,
    {{ surrogate_key(['run_id', 'contract_id']) }} as contract_key,
    run_id,
    suite_id,
    scenario,
    seed,
    scale,
    collection_event_id,
    contract_id,
    cast(event_timestamp as timestamp) as event_timestamp,
    channel,
    strategy,
    outcome,
    cast(promise_to_pay as boolean) as promise_to_pay,
    {{ money('promised_amount') }} as promised_amount,
    cast(promised_date as date) as promised_date,
    status
from {{ ref('raw_collection_events') }}
