select
    {{ surrogate_key(['run_id', 'installment_id']) }} as installment_key,
    {{ surrogate_key(['run_id', 'contract_id']) }} as contract_key,
    run_id,
    installment_id,
    contract_id,
    cast(installment_number as integer) as installment_number,
    cast(due_date as date) as due_date,
    {{ money('scheduled_principal') }} as scheduled_principal,
    {{ money('scheduled_interest') }} as scheduled_interest,
    {{ money('scheduled_fees') }} as scheduled_fees,
    {{ money('scheduled_total') }} as scheduled_total,
    status,
    {{ money('outstanding_balance') }} as outstanding_balance
from {{ ref('raw_installments') }}
