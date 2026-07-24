# Audit Summary

Generated from `reports/data_audit/quality_metrics.json` (produced by `uv run credlens data audit` in this session). Full narrative: `docs/data_quality_audit.md`.

| Source | Rows | Columns | Duplicate rows | Missing values | Findings | Status |
|---|---:|---:|---:|---:|---:|---|
| uci-default-credit | 30,000 | 25 | 0 | 0 | 1 (`documented_characteristic`) | Clean |
| south-german-credit | 1,000 | 21 | 0 | 0 | 0 | Clean |
| bcb-sgs-20570 | 137 | 2 | 0 | 0 | 2 (`documented_characteristic`, `hypothesis_requiring_investigation`) | Clean |
| bcb-sgs-21112 | 137 | 2 | 0 | 0 | 1 (`documented_characteristic`) | Clean |

All four sources: schema-comparison exact match (no unexpected/missing columns), zero exact-duplicate rows, zero missing values (confirming both UCI sources' own "no missing values" documentation), zero infinite values, zero constant columns.

One manually-discovered finding is **not** reflected in the table above because it's outside the automated tool's current scope (value-domain conformance, not column-presence): uci-default-credit's `EDUCATION` and `MARRIAGE` columns contain category codes outside UCI's documented ranges. See `docs/data_quality_audit.md` for the full detail and category (`confirmed_problem`).

One real bug was found and fixed during this session's acquisition, not left in the data: a BCB SGS date-window chunking artifact that produced one duplicate observation per series before the fix. See `docs/data_sources.md` for what happened and how it was caught by this same audit tooling.
