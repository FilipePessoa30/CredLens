-- Grain: one row per contract (run_id, contract_key). Per-contract
-- cure/relapse ("redefault") summary - cure_rate/redefault_rate
-- themselves are aggregates OVER this mart (see warehouse/kpi_catalog.yml
-- and warehouse/analyses/ for the exact aggregate queries), not columns
-- here, since a rate has no meaning at contract grain.
select
    run_id,
    suite_id,
    scenario,
    seed,
    scale,
    contract_key,
    contract_id,
    max(case when is_cure_month then 1 else 0 end) = 1 as was_ever_cured,
    sum(case when is_cure_month then 1 else 0 end) as cure_count,
    max(case when is_relapse_month then 1 else 0 end) = 1 as ever_relapsed,
    sum(case when is_relapse_month then 1 else 0 end) as relapse_count,
    (
        max(case when is_cure_month then 1 else 0 end) = 1
        and max(case when is_relapse_month then 1 else 0 end) = 1
    ) as redefaulted
from {{ ref('fct_account_monthly') }}
group by 1, 2, 3, 4, 5, 6, 7
