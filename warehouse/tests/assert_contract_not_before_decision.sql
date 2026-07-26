-- Temporal integrity (Phase 5 requirement): a contract can never
-- originate before its own decision. Re-asserted independently inside
-- the warehouse's own joined model - see assert_decision_not_before_submission.sql.
select
    application_key,
    contract_key,
    decision_timestamp,
    contract_date
from {{ ref('int_applications_decisions_contracts') }}
where contract_key is not null
  and decision_timestamp is not null
  and contract_date < decision_timestamp
