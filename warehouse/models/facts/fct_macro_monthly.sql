-- Grain: one row per (run_id, source_type, source_id, reference_date).
-- STOCK-like context fact (a macro observation for a given month) - real
-- BCB rows (is_synthetic=false) and, for macroeconomic_stress runs only,
-- synthetic_shock rows (is_synthetic=true), never blended into the same
-- row (see docs/adr/0008-macro-context-provenance.md, unchanged in the warehouse).
select
    macro_key,
    run_id,
    scenario,
    source_type,
    source_id,
    series_code,
    reference_date,
    value,
    unit,
    is_synthetic
from {{ ref('stg_macro_context_monthly') }}
