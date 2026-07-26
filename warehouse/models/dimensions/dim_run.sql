-- Grain: one row per generator run. Natural key: run_id (already globally
-- unique - it encodes scenario+scale+seed+config_hash by construction, see
-- credlens.generation.orchestrator._compute_generation_run_id). No SCD:
-- a run's own metadata is immutable once generated.
select
    run_id,
    generation_run_id,
    suite_id,
    parent_run_id,
    scenario,
    seed,
    scale,
    generator_version,
    contract_version_set,
    config_hash,
    period_start,
    period_end,
    generated_at,
    planned_customers,
    planned_applications
from {{ ref('stg_generation_runs') }}
