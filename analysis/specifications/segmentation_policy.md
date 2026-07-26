# Segmentation Policy (Phase 6 section 11, revised Phase 7 gate B)

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

## Minimum-observation policy (revised Phase 7 gate B)

Phase 6 used a single flat cutoff, `MIN_SEGMENT_OBSERVATIONS = 10` - judged,
in Phase 7, too low to sustain executive-facing reading (a 10-observation
cell is still dominated by single-contract noise). It is replaced by a
versioned, three-tier policy: `credlens.analysis.sample_policy`, loaded
from `analysis/specifications/segmentation_policy.yaml`.

| Classification | Condition | Meaning |
|---|---|---|
| `insufficient` | `n < insufficient_below` (default 30) | Never ranked, never recommended, never called out as best/worst. The count itself stays visible for audit only. |
| `limited` | `insufficient_below <= n < limited_below` (default 30-99) | Shown, with a visible caution label; avoid conclusive language. |
| `adequate` | `n >= limited_below` (default 100) | Shown without a suppression label - a descriptive-adequacy convention, **not** a formal statistical power guarantee. |

**Why 30/100**: 30 is the smallest sample size below which a single
contract's outcome can still swing a rate by several percentage points
in a way that reads as more precise than it is; 100 is a conventional,
easy-to-communicate floor for "large enough to describe without a
caveat" in an executive setting. Neither is a formal power calculation -
see `CLASSIFICATION_LABELS` in `credlens.analysis.sample_policy`, which
is deliberately worded to never claim statistical significance, a
confidence interval, or a margin of error.

**Enforcement**: every segmented query (`credlens.analysis.metrics`,
`credlens.analysis.scenarios`) adds both a `low_sample: bool` column (kept
for backward compatibility, `True` iff `sample_classification ==
"insufficient"`) and a `sample_classification: "insufficient" | "limited"
| "adequate"` column, rather than dropping rows - segmentation coverage
stays visible in the CSV/JSON output even where the metric itself should
not be quoted in a headline figure. Reports and the dashboard must not
rank, recommend, or cite an `insufficient` row's rate as a standalone
finding (`credlens.analysis.sample_policy.is_reportable`); `limited` rows
may be shown descriptively but never with conclusive language.
