-- Grain: one row per (run_id, snapshot_date). PAR30/60/90 (balance-weighted),
-- contract-count delinquency rates, mutually exclusive DPD buckets, new
-- delinquencies, and cures. Denominators are explicit per column name -
-- par30/60/90 divide by TOTAL portfolio balance that month; rate_30plus/
-- 60plus/90plus divide by TOTAL contract count that month. See
-- warehouse/kpi_catalog.yml for the exact formulas.
select
    run_id,
    suite_id,
    scenario,
    seed,
    scale,
    snapshot_date,
    count(*) as total_contracts,
    sum(total_balance) as total_balance,
    sum(case when dpd_bucket in ('30-59', '60-89', '90+') then 1 else 0 end) as contracts_30plus,
    sum(case when dpd_bucket in ('60-89', '90+') then 1 else 0 end) as contracts_60plus,
    sum(case when dpd_bucket = '90+' then 1 else 0 end) as contracts_90plus,
    sum(case when dpd_bucket in ('30-59', '60-89', '90+') then total_balance else 0 end) as balance_30plus,
    sum(case when dpd_bucket in ('60-89', '90+') then total_balance else 0 end) as balance_60plus,
    sum(case when dpd_bucket = '90+' then total_balance else 0 end) as balance_90plus,
    sum(case when contract_status = 'delinquent' and coalesce(prior_month_status, '') != 'delinquent' then 1 else 0 end) as new_delinquencies,
    sum(case when is_cure_month then 1 else 0 end) as cures,
    sum(case when is_relapse_month then 1 else 0 end) as relapses,
    sum(case when prior_month_status = 'delinquent' then 1 else 0 end) as prior_month_delinquent_count,
    case when sum(total_balance) > 0
        then sum(case when dpd_bucket in ('30-59', '60-89', '90+') then total_balance else 0 end) / sum(total_balance)
    end as par30,
    case when sum(total_balance) > 0
        then sum(case when dpd_bucket in ('60-89', '90+') then total_balance else 0 end) / sum(total_balance)
    end as par60,
    case when sum(total_balance) > 0
        then sum(case when dpd_bucket = '90+' then total_balance else 0 end) / sum(total_balance)
    end as par90,
    case when count(*) > 0
        then sum(case when dpd_bucket in ('30-59', '60-89', '90+') then 1 else 0 end)::double / count(*)
    end as rate_30plus,
    case when count(*) > 0
        then sum(case when dpd_bucket in ('60-89', '90+') then 1 else 0 end)::double / count(*)
    end as rate_60plus,
    case when count(*) > 0
        then sum(case when dpd_bucket = '90+' then 1 else 0 end)::double / count(*)
    end as rate_90plus,
    case when sum(case when prior_month_status = 'delinquent' then 1 else 0 end) > 0
        then sum(case when is_cure_month then 1 else 0 end)::double
             / sum(case when prior_month_status = 'delinquent' then 1 else 0 end)
    end as cure_rate
from {{ ref('fct_account_monthly') }}
group by 1, 2, 3, 4, 5, 6
