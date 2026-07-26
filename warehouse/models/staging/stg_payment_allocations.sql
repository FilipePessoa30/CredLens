select
    {{ surrogate_key(['run_id', 'allocation_id']) }} as allocation_key,
    {{ surrogate_key(['run_id', 'payment_id']) }} as payment_key,
    {{ surrogate_key(['run_id', 'installment_id']) }} as installment_key,
    {{ surrogate_key(['run_id', 'contract_id']) }} as contract_key,
    run_id,
    allocation_id,
    payment_id,
    installment_id,
    contract_id,
    {{ money('allocated_principal') }} as allocated_principal,
    {{ money('allocated_interest') }} as allocated_interest,
    {{ money('allocated_fees') }} as allocated_fees,
    {{ money('allocated_total') }} as allocated_total
from {{ ref('raw_payment_allocations') }}
