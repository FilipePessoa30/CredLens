-- DPD bucket structural invariant (Phase 5 requirement: mutually
-- exclusive buckets with sums that reconcile). dpd_bucket itself is a
-- single column per row (a contract cannot be in two buckets
-- simultaneously - mutual exclusivity is structural, not something a
-- query can violate). What CAN break is the cumulative "N+" rollup used
-- throughout the marts: 90+ must always be a subset of 60+, which must
-- always be a subset of 30+, which must never exceed the snapshot's own
-- total_contracts.
select
    run_id,
    snapshot_date,
    contracts_30plus,
    contracts_60plus,
    contracts_90plus,
    total_contracts
from {{ ref('mart_delinquency_monthly') }}
where not (
    contracts_90plus <= contracts_60plus
    and contracts_60plus <= contracts_30plus
    and contracts_30plus <= total_contracts
)
