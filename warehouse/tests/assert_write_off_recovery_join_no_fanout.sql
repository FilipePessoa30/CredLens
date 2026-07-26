-- Absence of join-caused duplication (Phase 5 requirement). int_write_off_recovery
-- left-joins stg_write_off_events to stg_recovery_events - a write-off has
-- AT MOST one recovery by DGP construction (see
-- credlens.generation.recoveries's own docstring), so this join must never
-- fan out into more than one row per write_off_key.
select write_off_key, count(*) as row_count
from {{ ref('int_write_off_recovery') }}
group by write_off_key
having count(*) > 1
