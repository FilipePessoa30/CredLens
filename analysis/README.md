# CredLens Portfolio Analysis Layer (Phase 6)

Reproducible, SQL-first analysis over the DuckDB + dbt warehouse built in
Phase 5. This directory holds the non-code analysis artifacts; the
executable layer lives in `src/credlens/analysis/`.

## Layout

- `questions.yml` - versioned business-question registry (section 9). Every
  question links to the exact function that answers it (SQL-first, see
  `src/credlens/analysis/metrics.py`) and the table/figure it produces.
- `specifications/` - written policy documents that apply across many
  questions (e.g. the minimum-sample-size suppression rule) rather than
  living inside any single query's docstring.

## Why there is no `queries/` or `templates/` directory

The suggested Phase 6 structure listed `analysis/queries/` and
`analysis/templates/`. This repo intentionally does not have them:

- **Queries**: every SQL statement the analysis layer runs is either (a) an
  already-tested dbt mart under `warehouse/models/marts/`, queried through
  `credlens.analysis.metrics._mart()`, or (b) an ad hoc segmentation query
  documented inline (purpose/grain/filters/nulls) directly above its
  Python function in `src/credlens/analysis/metrics.py`. Copying that SQL
  into a second, unexecuted `.sql` file under `analysis/queries/` would
  create exactly the kind of unmaintained, drift-prone duplicate the
  SQL-first requirement (section 10) is meant to prevent - the inline SQL
  *is* the single source of truth, and it is exercised by
  `tests/test_analysis_metrics.py` against a real build on every test run.
- **Templates**: `credlens.analysis.reporting` builds Markdown directly in
  Python (`decision_card()`, `build_executive_summary()`,
  `build_technical_report()`) from DataFrames/dicts a run itself computed.
  There is no Jinja (or similar) template file to keep in sync with that
  code, so an empty `templates/` directory would be dead scaffolding.

## Running an analysis

```bash
uv run credlens warehouse build --suite-id SUITE_sample_2026
uv run credlens analysis validate --build-id <build_id>
uv run credlens analysis run --build-id <build_id>
```

Output goes to `reports/portfolio_analysis/` by default (`--output-dir` to
override; `--force` to overwrite an existing run there). See
`reports/portfolio_analysis/README.md` for what gets written, and
`docs/warehouse_architecture.md` / the Phase 6 technical report for the
full analytical architecture.

## Scope

Out of scope for this layer, per the Phase 6 brief: trained predictive
models, cutoff optimization, profit/LGD/EAD/regulatory-PD calculations,
and any definitive real-world policy recommendation. Every output is a
result of a synthetic data-generation process (DGP), never a claim about
a real financial institution.

Phase 7 added `credlens.analysis.sample_policy` (three-tier minimum-
sample classification), `credlens.analysis.data_provenance` (five-
category source classification), `credlens.analysis.robustness`
(multi-scenario multi-seed sweep), and `credlens.analysis.insights` (the
generated, versioned insights registry) - still no business logic beyond
what already lived here, and still no dashboard. The dashboard itself
(`src/credlens/dashboard/`, `dashboard/`) is a separate, presentation-only
layer that reuses everything in this package rather than duplicating it -
see `dashboard/README.md`.
