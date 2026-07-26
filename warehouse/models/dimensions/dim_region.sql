-- Grain: one row per distinct region actually observed in
-- fairness_attributes (evaluation-only - see docs/fairness_data_design.md;
-- this dimension exists for aggregate, retrospective audit joins, never
-- as a fact-table filter used to target an individual).
select distinct
    region as region_key,
    region
from {{ ref('stg_fairness_attributes') }}
where region is not null
