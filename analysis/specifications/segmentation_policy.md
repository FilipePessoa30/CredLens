# Segmentation Policy (Phase 6 section 11)

Applies to every segmented breakdown produced by
`src/credlens/analysis/metrics.py` (funnel by channel, portfolio by
region x channel, approval rate by policy version) and
`src/credlens/analysis/scenarios.py` (composition vs. performance).

## Permitted segmentation attributes

Only attributes that already exist in the warehouse and are permitted for
aggregate, retrospective analysis:

- `product`, `channel` (from `fct_applications`)
- `region` (from `stg_fairness_attributes` - **evaluation-only**, see
  `docs/fairness_data_design.md`; used strictly as an aggregate audit
  breakdown, never joined into any decisioning path or used to target an
  individual application)
- `policy_version_id` (from `dim_policy`)
- `bureau_score_bucket`, `income_band`, `contract_value_band` (from the
  relevant fact tables, where present)
- `vintage_month` / `months_on_book` (cohort/MOB, from `mart_vintage_cohorts`)
- `scenario` (from `dim_run`)

These are mutually exclusive within a single `group by` (a row belongs to
exactly one channel, one region, one policy version, etc.) and, where a
query groups by one such attribute alone, collectively exhaustive over the
population the query's own `where` clause selects (documented per-function
in `metrics.py`'s docstrings).

Sensitive attributes (anything in `stg_fairness_attributes` beyond the
aggregate `region` breakdown above) are **not** used to recommend credit
policy in this phase - fairness/bias analysis is out of scope until a
dedicated phase with its own methodology.

## Minimum-observation threshold

`MIN_SEGMENT_OBSERVATIONS = 10` (`src/credlens/analysis/metrics.py`).

**Why 10**: below 10 observations, a single contract's outcome can swing a
rate by more than 10 percentage points (`1/9 ≈ 11.1%`) - the metric would
read as more statistically precise than it actually is. This is a
simplicity-first, defensible floor, not a claim of formal statistical
power; it exists to prevent a single-digit-observation cell from being read
as a stable rate.

**Enforcement**: every segmented query adds a `low_sample: bool` column
(`row_count < MIN_SEGMENT_OBSERVATIONS`) rather than dropping rows -
segmentation coverage stays visible in the CSV/JSON output even where the
metric itself should not be quoted in a headline figure. Reports built from
these tables (`credlens.analysis.reporting`) must not cite a `low_sample`
row's rate as a standalone finding.
