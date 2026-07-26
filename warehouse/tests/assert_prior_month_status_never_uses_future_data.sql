-- DELIBERATE temporal-leakage test (Phase 5 requirement: "at least one
-- deliberate test that WOULD fail if a transformation used future data").
--
-- int_contract_monthly_enriched derives prior_month_status via
-- lag(contract_status) over (partition by contract_key order by
-- snapshot_date). This test recomputes each contract's TRUE prior-month
-- status independently - via a correlated subquery finding the row with
-- the largest snapshot_date strictly LESS than the current one - and
-- compares it to the model's own prior_month_status. If a future change
-- ever let a LATER snapshot leak into this column (e.g. lag() flipped to
-- lead(), a wrong ORDER BY direction, or a join condition allowing
-- snapshot_date >= instead of <), this test fails immediately: any
-- mismatch is proof that a historical metric was computed using
-- information that would not have been available at that point in time.
with true_prior as (
    select
        curr.contract_key,
        curr.snapshot_date,
        (
            select p.contract_status
            from {{ ref('int_contract_monthly_enriched') }} p
            where p.contract_key = curr.contract_key
              and p.snapshot_date < curr.snapshot_date
            order by p.snapshot_date desc
            limit 1
        ) as true_prior_status
    from {{ ref('int_contract_monthly_enriched') }} curr
)
select
    e.contract_key,
    e.snapshot_date,
    e.prior_month_status as model_prior_status,
    tp.true_prior_status
from {{ ref('int_contract_monthly_enriched') }} e
join true_prior tp
    on e.contract_key = tp.contract_key and e.snapshot_date = tp.snapshot_date
where coalesce(e.prior_month_status, '~NULL~') != coalesce(tp.true_prior_status, '~NULL~')
