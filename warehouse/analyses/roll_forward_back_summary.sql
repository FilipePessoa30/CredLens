-- KPIs DEL-011/DEL-012/DEL-013 (roll_forward_count / roll_back_count /
-- bucket_stability_rate) - see warehouse/kpi_catalog.yml. Classifies each
-- mart_roll_rates transition as forward (worse), back (better), or stable
-- by comparing dim_dpd_bucket.sort_order for from_bucket vs. to_bucket -
-- never compares different contracts, only a contract's own consecutive
-- months (mart_roll_rates is already scoped that way - see its own header
-- comment).
with classified as (
    select
        r.run_id,
        r.suite_id,
        r.scenario,
        r.seed,
        r.scale,
        r.snapshot_date,
        r.contract_count,
        case
            when to_b.sort_order > from_b.sort_order then 'forward'
            when to_b.sort_order < from_b.sort_order then 'back'
            else 'stable'
        end as roll_direction
    from {{ ref('mart_roll_rates') }} r
    join {{ ref('dim_dpd_bucket') }} from_b on r.from_bucket = from_b.dpd_bucket
    join {{ ref('dim_dpd_bucket') }} to_b on r.to_bucket = to_b.dpd_bucket
)
select
    run_id,
    suite_id,
    scenario,
    seed,
    scale,
    snapshot_date,
    sum(case when roll_direction = 'forward' then contract_count else 0 end) as roll_forward_count,
    sum(case when roll_direction = 'back' then contract_count else 0 end) as roll_back_count,
    sum(case when roll_direction = 'stable' then contract_count else 0 end) as stable_count,
    sum(contract_count) as total_transitions,
    case when sum(contract_count) > 0
        then sum(case when roll_direction = 'stable' then contract_count else 0 end)::double
             / sum(contract_count)
    end as bucket_stability_rate
from classified
group by 1, 2, 3, 4, 5, 6
