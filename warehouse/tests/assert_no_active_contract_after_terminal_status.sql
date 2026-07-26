-- Temporal integrity (Phase 5 requirement): "a terminal contract must not
-- reappear as active." Once a contract reaches settled/closed/charged_off
-- in one snapshot month, it must never show active/delinquent in any
-- LATER snapshot month - a terminal status is terminal.
select
    t.contract_key,
    t.snapshot_date as terminal_date,
    t.contract_status as terminal_status,
    later.snapshot_date as later_date,
    later.contract_status as later_status
from {{ ref('fct_account_monthly') }} t
join {{ ref('fct_account_monthly') }} later
    on t.contract_key = later.contract_key
    and later.snapshot_date > t.snapshot_date
where t.contract_status in ('settled', 'closed', 'charged_off')
  and later.contract_status in ('active', 'delinquent')
