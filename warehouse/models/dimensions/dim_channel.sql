-- Grain: one row per distinct application channel actually observed
-- (app/web/branch/partner in baseline.generation.yaml - not hardcoded
-- here, derived from real data).
select distinct
    channel as channel_key,
    channel
from {{ ref('stg_applications') }}
where channel is not null
