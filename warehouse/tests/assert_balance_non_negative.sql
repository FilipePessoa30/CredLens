-- Financial sanity (Phase 5 requirement): non-negative balance, no
-- documented exception - a contract's outstanding balance is never
-- negative in this DGP (a prepayment settles to exactly 0, it does not
-- overshoot into credit).
select contract_key, snapshot_date, total_balance
from {{ ref('fct_account_monthly') }}
where total_balance < 0
