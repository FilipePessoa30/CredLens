-- KPI SCN-007 (pre_shock_identity_check) - see warehouse/kpi_catalog.yml
-- and mart_macro_stress_pre_post.sql's own header comment. The DGP
-- deliberately makes pre-shock payment behavior byte-identical between
-- baseline and macroeconomic_stress for the same seed - if this ever
-- stops holding, mart_macro_stress_pre_post's own pre_shock row would
-- show a real delta, which is exactly what this test asserts never
-- happens (beyond floating-point noise).
select
    suite_id,
    period,
    par90_delta_abs,
    dpd90_rate_delta_abs,
    write_off_count_delta_abs
from {{ ref('mart_macro_stress_pre_post') }}
where period = 'pre_shock'
  and (
    abs(par90_delta_abs) > 1e-9
    or abs(dpd90_rate_delta_abs) > 1e-9
    or write_off_count_delta_abs != 0
  )
