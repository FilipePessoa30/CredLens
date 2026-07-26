-- Grain: one row per collection (contact) event. FLOW event. FK:
-- contract_key -> fct_contracts.
select
    collection_event_key,
    contract_key,
    run_id,
    suite_id,
    scenario,
    seed,
    scale,
    collection_event_id,
    event_timestamp,
    date_trunc('month', event_timestamp) as event_month,
    channel,
    strategy,
    outcome,
    promise_to_pay,
    promised_amount,
    promised_date,
    status as collection_status
from {{ ref('stg_collection_events') }}
