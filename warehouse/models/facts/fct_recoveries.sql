-- Grain: one row per recovery event. FLOW event. FK: write_off_key ->
-- fct_writeoffs, contract_key -> fct_contracts. Additive measure: amount.
select
    recovery_key,
    contract_key,
    write_off_key,
    run_id,
    recovery_id,
    recovery_date,
    date_trunc('month', recovery_date) as recovery_month,
    amount as recovery_amount,
    channel as recovery_channel,
    source as recovery_source
from {{ ref('stg_recovery_events') }}
