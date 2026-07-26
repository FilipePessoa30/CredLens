-- Defense in depth (Phase 5 requirement: absence of quarantine). Source
-- selection (credlens.warehouse.sources.resolve_sources) already refuses
-- to load a run whose manifest status isn't 'completed', and separately
-- refuses any path under data/quarantine/ - this test re-asserts the same
-- invariant INSIDE the warehouse itself: every run's own self-reported
-- status, once materialized here, must be 'completed'. A quarantined run
-- is written with status 'quarantined_expected_failure' and is never
-- promoted to data/synthetic/, so this should always be empty; it exists
-- to catch any future change to source selection that might weaken that
-- guarantee without a warehouse-layer test noticing.
select run_id, status
from {{ ref('stg_generation_runs') }}
where status != 'completed'
