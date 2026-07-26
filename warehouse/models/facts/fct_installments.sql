-- Grain: one row per installment. FLOW/schedule fact - the amortization
-- plan, not a payment. FK: contract_key -> fct_contracts. Additive
-- measures: scheduled_principal/interest/fees/total (safe to sum per
-- contract - see docs/synthetic_generation_implementation.md "Financial
-- precision": these reconcile exactly to financed_amount).
select
    installment_key,
    contract_key,
    run_id,
    installment_id,
    installment_number,
    due_date,
    date_trunc('month', due_date) as due_month,
    scheduled_principal,
    scheduled_interest,
    scheduled_fees,
    scheduled_total,
    status as installment_status,
    outstanding_balance
from {{ ref('stg_installments') }}
