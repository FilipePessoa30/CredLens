-- KPI DEL-010 (redefault_rate) - see warehouse/kpi_catalog.yml.
-- Of contracts that were EVER cured, the fraction that later relapsed
-- into delinquency again. was_ever_cured/ever_relapsed are both derived
-- purely from the contract's own status time series (see
-- int_contract_monthly_enriched and docs/adr/0010-cure-semantics-and-relapse.md)
-- - never a stored/redundant operational column.
--
-- `dbt compile` renders this to warehouse/target/compiled/.../redefault_rate.sql
-- for ad-hoc execution against a built warehouse; it is not materialized
-- as a table/view (analyses are documentation-as-code, not part of the DAG).
select
    run_id,
    suite_id,
    scenario,
    seed,
    scale,
    count(*) as contracts_ever_cured,
    sum(case when redefaulted then 1 else 0 end) as contracts_redefaulted,
    case when count(*) > 0
        then sum(case when redefaulted then 1 else 0 end)::double / count(*)
    end as redefault_rate
from {{ ref('mart_cure_and_redefault') }}
where was_ever_cured
group by 1, 2, 3, 4, 5
