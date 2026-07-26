select
    {{ surrogate_key(['run_id', 'payment_id']) }} as payment_key,
    {{ surrogate_key(['run_id', 'contract_id']) }} as contract_key,
    {{ surrogate_key(['run_id', 'customer_id']) }} as customer_key,
    case
        when reversal_of_payment_id is not null
        then {{ surrogate_key(['run_id', 'reversal_of_payment_id']) }}
        else null
    end as reversal_of_payment_key,
    run_id,
    payment_id,
    contract_id,
    customer_id,
    cast(payment_timestamp as timestamp) as payment_timestamp,
    {{ money('amount') }} as amount,
    channel,
    status,
    cast(settlement_date as date) as settlement_date,
    reversal_of_payment_id,
    payment_type,
    (reversal_of_payment_id is not null) as is_reversal
from {{ ref('raw_payments') }}
