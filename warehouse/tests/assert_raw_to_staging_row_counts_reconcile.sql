-- Reconciliation between raw and staging (Phase 5 requirement). Staging
-- is a thin 1:1 rename/cast layer (see docs/warehouse_architecture.md) -
-- no staging model may add or drop rows vs. its own raw source. Any
-- mismatch here means a staging model introduced an accidental filter or
-- a join-caused fan-out.
with raw_counts as (
    select 'customers' as table_name, count(*) as row_count from {{ ref('raw_customers') }}
    union all
    select 'applications', count(*) from {{ ref('raw_applications') }}
    union all
    select 'contracts', count(*) from {{ ref('raw_contracts') }}
    union all
    select 'installments', count(*) from {{ ref('raw_installments') }}
    union all
    select 'payments', count(*) from {{ ref('raw_payments') }}
    union all
    select 'account_monthly_snapshots', count(*) from {{ ref('raw_account_monthly_snapshots') }}
    union all
    select 'write_off_events', count(*) from {{ ref('raw_write_off_events') }}
    union all
    select 'recovery_events', count(*) from {{ ref('raw_recovery_events') }}
),
staging_counts as (
    select 'customers' as table_name, count(*) as row_count from {{ ref('stg_customers') }}
    union all
    select 'applications', count(*) from {{ ref('stg_applications') }}
    union all
    select 'contracts', count(*) from {{ ref('stg_contracts') }}
    union all
    select 'installments', count(*) from {{ ref('stg_installments') }}
    union all
    select 'payments', count(*) from {{ ref('stg_payments') }}
    union all
    select 'account_monthly_snapshots', count(*) from {{ ref('stg_account_monthly_snapshots') }}
    union all
    select 'write_off_events', count(*) from {{ ref('stg_write_off_events') }}
    union all
    select 'recovery_events', count(*) from {{ ref('stg_recovery_events') }}
)
select
    r.table_name,
    r.row_count as raw_row_count,
    s.row_count as staging_row_count
from raw_counts r
join staging_counts s on r.table_name = s.table_name
where r.row_count != s.row_count
