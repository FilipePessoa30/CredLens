-- Temporal integrity (Phase 5 requirement): an application can never be
-- decided before it was submitted. Enforced at generation time by the
-- generator's own DECISION_BEFORE_SUBMISSION business rule - this test
-- re-asserts the same invariant independently, inside the warehouse's own
-- joined model, so a warehouse-layer bug (e.g. a wrong join key) cannot
-- silently produce an impossible timeline without being caught here too.
select
    application_key,
    decision_key,
    submitted_at,
    decision_timestamp
from {{ ref('int_applications_decisions_contracts') }}
where decision_timestamp is not null
  and decision_timestamp < submitted_at
