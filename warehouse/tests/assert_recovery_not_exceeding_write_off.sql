-- Financial sanity (Phase 5 requirement): recovery must never exceed what
-- the DGP rule permits - a recovery cannot exceed the amount originally
-- written off on that same contract (see docs/business_rules.md's
-- recovery rule).
select write_off_key, write_off_amount, recovery_amount
from {{ ref('int_write_off_recovery') }}
where recovery_amount is not null
  and recovery_amount > write_off_amount
