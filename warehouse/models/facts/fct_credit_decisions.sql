-- Grain: one row per decision. FLOW event. FK: application_key ->
-- fct_applications, policy_version_key -> dim_policy, run_id -> dim_run.
-- Additive measures: approved_amount (only meaningful for outcome='approved',
-- null otherwise - never summed without filtering on outcome first).
select
    decision_key,
    application_key,
    policy_version_key,
    run_id,
    decision_id,
    decision_timestamp,
    date_trunc('month', decision_timestamp) as decision_month,
    outcome,
    reason_code,
    approved_amount,
    approved_term_months,
    offered_rate,
    is_final
from {{ ref('stg_credit_decisions') }}
