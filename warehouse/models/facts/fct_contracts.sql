-- Grain: one row per contract. FLOW event (origination). FK: customer_key
-- -> dim_customer, application_key -> fct_applications, run_id -> dim_run.
-- Additive measure: financed_amount (one origination, one amount - safe
-- to sum "total originated" within a run/period). `status` here is the
-- contract's CURRENT (as-of-generation-time) status, not a time series -
-- see fct_account_monthly for the monthly STOCK view.
select
    contract_key,
    application_key,
    customer_key,
    run_id,
    suite_id,
    scenario,
    seed,
    scale,
    contract_id,
    contract_date,
    disbursement_date,
    date_trunc('month', disbursement_date) as vintage_month,
    financed_amount,
    term_months,
    contract_rate,
    num_installments,
    first_due_date,
    status as contract_status,
    currency_unit,
    closed_date
from {{ ref('stg_contracts') }}
