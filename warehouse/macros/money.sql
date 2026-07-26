{#
  Casts a monetary column to a fixed-point DECIMAL(18,2) instead of DOUBLE.

  Source parquet stores every amount as float64 (the generator's pandas/
  pyarrow write path has no native Decimal dtype - see
  credlens.generation.payments's own Decimal-based ledger, which IS exact
  up to the parquet write). Staging DOUBLE casts were found to make
  SUM()/AVG() in the marts layer non-deterministic across otherwise
  identical rebuilds: DuckDB parallelizes aggregation across threads, and
  float64 addition is not associative, so two builds from the same inputs
  could each round the last one or two digits differently depending on
  thread scheduling - breaking the idempotency guarantee (same inputs must
  produce the same analytical fingerprint). Casting to DECIMAL(18,2) here
  makes every downstream SUM/AVG exact fixed-point arithmetic, which is
  associative and therefore thread-order-independent - see
  docs/warehouse_architecture.md#determinism-and-decimal-money and the two
  real BUILD_* runs compared while diagnosing this (mart_portfolio_monthly,
  mart_delinquency_monthly, mart_roll_rates, mart_vintage_cohorts all
  differed at the ~1e-11 relative ULP level before this fix).

  Only genuine currency amounts should use this - rates/ratios (contract_rate,
  offered_rate, debt_to_income) are intentionally left as DOUBLE.
#}
{% macro money(column_name) %}
    cast({{ column_name }} as decimal(18, 2))
{% endmacro %}
