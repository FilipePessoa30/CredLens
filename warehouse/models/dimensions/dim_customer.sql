-- Grain: one row per (run_id, customer_id). Natural key: (run_id,
-- customer_id) - customer_id alone is NOT unique across runs that share
-- common random numbers (Phase 5 section 6). No SCD Type 2: this DGP
-- never mutates a customer's own attributes after creation (there are
-- none beyond created_at - see credlens/generation/population.py's own
-- docstring on why no demographic/latent field lives on customers at
-- all) - so there is no history to version.
select
    customer_key,
    run_id,
    customer_id,
    created_at
from {{ ref('stg_customers') }}
