-- Cross-run key isolation, as an actual dbt test (Phase 5 requirement) -
-- not just the manual query used to first prove this (see
-- docs/warehouse_architecture.md). CRN scenarios legitimately reuse the
-- SAME natural customer_id across different runs (see
-- docs/common_random_numbers.md) - surrogate_key(run_id, natural_id) must
-- still produce a distinct customer_key per run. This test fails if a
-- natural customer_id shared by N different runs does NOT yield exactly N
-- distinct customer_keys (i.e. a real collision, or an accidental key
-- collapse across runs).
select
    customer_id,
    count(distinct run_id) as run_count,
    count(distinct customer_key) as distinct_key_count
from {{ ref('stg_customers') }}
group by customer_id
having count(distinct run_id) > 1
   and count(distinct customer_key) != count(distinct run_id)
