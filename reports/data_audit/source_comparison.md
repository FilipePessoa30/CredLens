# Source Comparison

A structural, side-by-side comparison of the four acquired sources. **This is a comparison of dataset structure and provenance, not a comparison of the underlying populations** - Taiwan (2005), Germany (1973-1975), and Brazil (aggregate, 2015-2026) are different countries and eras, and nothing here treats them as one comparable population. See `docs/assumptions_and_limitations.md` and `docs/sensitive_attributes.md`.

| Property | uci-default-credit | south-german-credit | bcb-sgs-20570 | bcb-sgs-21112 |
|---|---|---|---|---|
| Country | Taiwan | Germany | Brazil | Brazil |
| Period | Apr-Sep 2005 | 1973-1975 | 2015-2026 (queried range) | 2015-2026 (queried range) |
| Granularity | Individual client | Individual applicant | National aggregate | National aggregate |
| Rows | 30,000 | 1,000 | 137 | 137 |
| Columns | 25 | 21 | 2 | 2 |
| Has a target variable | Yes (`Y`, binary) | Yes (`kredit`, binary) | No (macro indicator) | No (macro indicator) |
| License | CC BY 4.0 | CC BY 4.0 | ODbL 1.0 | ODbL 1.0 |
| Format acquired | CSV | ZIP (asc + docs) | JSON | JSON |
| Role | `primary_benchmark` | `secondary_benchmark` | `market_context` | `market_context` |
| Longitudinal structure | Partial (6 months embedded as columns) | None (single snapshot) | Yes (monthly time series) | Yes (monthly time series) |
| Multi-table/relational | No | No | No | No |

## What this comparison is useful for

- Confirming the two individual-level benchmarks are structurally different enough (size, era, feature richness) that a future modeling phase should not treat them as interchangeable or combinable - see `docs/dataset_selection.md`.
- Confirming the two BCB series share the same shape (`data`, `valor`) and can use the same acquisition/audit code path, which they do (`credlens.data.bcb_client`, `credlens.data.audit`).
- Making explicit that only the two BCB series have real longitudinal (time-series) structure - a `structural_limitation` recorded for both UCI datasets in `docs/data_quality_audit.md` and a key reason `docs/data_strategy.md` still calls for a future synthetic operational layer to support vintage/roll-rate analysis.

## What this comparison is not useful for

Computing a blended statistic across rows from different sources (e.g., an average default rate across uci-default-credit and south-german-credit) would silently mix two unrelated populations and is exactly the kind of error `docs/assumptions_and_limitations.md` and this Phase 2 brief prohibit. No such computation appears anywhere in this project.
