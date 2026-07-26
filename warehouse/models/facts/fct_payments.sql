-- Grain: one row per payment transaction (including reversals - a
-- reversal is its OWN row, never a negative amount - see
-- contracts/operational/payments.yaml). FLOW event. FK: contract_key ->
-- fct_contracts, customer_key -> dim_customer. Additive measure: amount,
-- BUT summing it directly double-counts a reversed payment - use
-- net_amount (amount, or -amount for a reversal row) when aggregating
-- "money actually collected". payment_type (Phase 5) is the generator's
-- own explicit classification - see docs/adr/0010-cure-semantics-and-relapse.md.
select
    payment_key,
    contract_key,
    customer_key,
    reversal_of_payment_key,
    run_id,
    payment_id,
    payment_timestamp,
    date_trunc('month', payment_timestamp) as payment_month,
    amount,
    case when is_reversal then -amount else amount end as net_amount,
    channel,
    status as payment_status,
    settlement_date,
    payment_type,
    is_reversal
from {{ ref('stg_payments') }}
