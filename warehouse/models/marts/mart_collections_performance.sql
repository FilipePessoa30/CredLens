-- Grain: one row per (run_id, event_month). Collections activity vs. the
-- delinquent population eligible that month - contact_rate's denominator
-- is contracts_eligible (delinquent that month), not total portfolio.
-- Never presented as a causal effect of an individual contact (see
-- docs/counterfactual_scenarios.md's collections_change caveat,
-- unchanged) - this is descriptive collections activity only.
with collections as (
    select
        run_id,
        suite_id,
        scenario,
        seed,
        scale,
        event_month,
        count(*) as contact_events,
        count(distinct contract_key) as contracts_contacted,
        sum(case when promise_to_pay then 1 else 0 end) as promises_to_pay
    from {{ ref('fct_collections') }}
    group by 1, 2, 3, 4, 5, 6
),
eligible as (
    select
        run_id,
        date_trunc('month', snapshot_date) as month,
        count(distinct contract_key) as contracts_eligible
    from {{ ref('fct_account_monthly') }}
    where contract_status = 'delinquent'
    group by 1, 2
)
select
    c.*,
    coalesce(e.contracts_eligible, 0) as contracts_eligible,
    case when e.contracts_eligible > 0
        then c.contracts_contacted::double / e.contracts_eligible
    end as contact_rate,
    case when c.contracts_contacted > 0
        then c.promises_to_pay::double / c.contracts_contacted
    end as promise_rate
from collections c
left join eligible e
    on c.run_id = e.run_id
    and c.event_month = e.month
