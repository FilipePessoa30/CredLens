-- Financial reconciliation (Phase 5 requirement). total_balance must
-- equal the sum of its own components - a 1-cent tolerance absorbs
-- DECIMAL(18,2) rounding, nothing more (see warehouse/macros/money.sql).
select
    contract_key,
    snapshot_date,
    outstanding_principal,
    outstanding_interest,
    outstanding_fees,
    total_balance,
    (outstanding_principal + outstanding_interest + outstanding_fees) as computed_total
from {{ ref('fct_account_monthly') }}
where abs(total_balance - (outstanding_principal + outstanding_interest + outstanding_fees)) > 0.01
