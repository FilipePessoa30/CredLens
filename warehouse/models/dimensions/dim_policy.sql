-- Grain: one row per (run_id, policy_version_id). Every scenario in this
-- DGP has exactly one policy_versions row (docs/synthetic_calibration.md:
-- the richer mid-period policy-switch design remains requires_calibration) -
-- so this dimension has no history to version within a run either.
select
    policy_version_key,
    run_id,
    policy_version_id,
    policy_name,
    policy_version_number,
    effective_from,
    effective_to,
    status,
    rules_reference,
    change_reason
from {{ ref('stg_policy_versions') }}
