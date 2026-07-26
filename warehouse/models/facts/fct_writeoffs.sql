-- Grain: one row per write-off (charge-off) event. FLOW event, terminal
-- for its contract. FK: contract_key -> fct_contracts. Additive measure:
-- amount (one charge-off, one loss amount).
select
    write_off_key,
    contract_key,
    run_id,
    write_off_id,
    write_off_date,
    date_trunc('month', write_off_date) as write_off_month,
    write_off_amount,
    write_off_principal,
    write_off_interest,
    write_off_fees,
    reason,
    policy_reference,
    has_recovery,
    days_to_recovery,
    recovery_rate
from {{ ref('int_write_off_recovery') }}
