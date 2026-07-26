-- One row per application, left-joined forward through its (at most one)
-- final decision and (at most one) resulting contract - the funnel
-- backbone: submitted -> decisioned -> approved -> booked. An approval
-- never implies a contract (booking_rate_given_approved < 1 in every
-- scenario config) - is_approved and is_booked are independent flags on
-- purpose.
select
    a.application_key,
    a.customer_key,
    a.run_id,
    a.suite_id,
    a.scenario,
    a.seed,
    a.scale,
    a.application_id,
    a.customer_id,
    a.submitted_at,
    a.channel,
    a.product,
    a.requested_amount,
    a.requested_term_months,
    a.status as application_status,
    d.decision_key,
    d.decision_id,
    d.decision_timestamp,
    d.outcome as decision_outcome,
    d.reason_code,
    d.approved_amount,
    d.approved_term_months,
    d.offered_rate,
    c.contract_key,
    c.contract_id,
    c.contract_date,
    c.disbursement_date,
    c.financed_amount,
    c.status as contract_status,
    (a.status != 'cancelled') as was_decided,
    (d.outcome = 'approved') as is_approved,
    (c.contract_key is not null) as is_booked
from {{ ref('stg_applications') }} a
left join {{ ref('stg_credit_decisions') }} d on a.application_key = d.application_key
left join {{ ref('stg_contracts') }} c on a.application_key = c.application_key
