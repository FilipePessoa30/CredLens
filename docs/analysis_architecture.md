# Portfolio Analysis Architecture (Phase 6)

This document describes the **implemented** reproducible analysis layer under `src/credlens/analysis/`, `analysis/`, and `reports/portfolio_analysis/`. It is the as-built companion to `docs/warehouse_architecture.md` (the layer this one queries) and `analysis/questions.yml` (the business-question registry this layer answers).

**Everything this layer produces describes a synthetic portfolio.** No number here represents a real financial institution - see `docs/assumptions_and_limitations.md`, and every generated report/notebook repeats this warning explicitly.

## Contents

- [Why this layer, and what it is not](#why-this-layer-and-what-it-is-not)
- [Module map](#module-map)
- [SQL-first discipline](#sql-first-discipline)
- [Segmentation and the minimum-sample rule](#segmentation-and-the-minimum-sample-rule)
- [Scenario pairing: composition vs. performance](#scenario-pairing-composition-vs-performance)
- [Multi-seed robustness](#multi-seed-robustness)
- [Public benchmark appendix](#public-benchmark-appendix)
- [Provenance manifest](#provenance-manifest)
- [The `credlens analysis` CLI](#the-credlens-analysis-cli)
- [Output tree](#output-tree)
- [Running it](#running-it)
- [Limitations](#limitations)

## Why this layer, and what it is not

Phase 5 built a warehouse that can answer questions if you already know the SQL to ask. Phase 6 turns that into a reproducible, versioned analysis: a fixed registry of business questions (`analysis/questions.yml`), each answered by a tested Python function that wraps a specific SQL query or dbt mart, rendered into bilingual (EN/PT-BR) reports and professional charts, all traceable back to the exact build that produced them via a provenance manifest.

It is explicitly **not** a dashboard, not a trained predictive model, not a cutoff-optimization tool, and makes no profit/LGD/EAD/regulatory-PD claim - none of these has supporting data in the DGP, and building them was out of scope for this phase (see `docs/roadmap.md`).

## Module map

| Module | Responsibility |
|---|---|
| `credlens.analysis.validation` | Gates a build before anything else touches it: build exists, dbt tests all passed, `final_status == "success"`, `analytical_fingerprint` present, raw sources re-verified (reuses `credlens.warehouse.integrity.verify_build_sources` - Phase 6 gate C). |
| `credlens.analysis.metrics` | SQL-first query functions - either a thin wrapper around an existing dbt mart (`_mart()`), or a documented ad hoc query for a segmentation no mart covers. Every function takes an open DuckDB connection and returns a `pandas.DataFrame`; no business logic is reimplemented in pandas. |
| `credlens.analysis.scenarios` | Paired scenario comparison - `composition_vs_performance()` splits a policy scenario's booked population into shared/baseline-only/scenario-only by `application_id` (never `contract_id` - see [Scenario pairing](#scenario-pairing-composition-vs-performance)). |
| `credlens.analysis.multiseed` | Wraps `credlens.generation.montecarlo.run_monte_carlo` (Phase 4B) and labels the result "simulation variability" - never a statistical confidence interval. |
| `credlens.analysis.benchmark` | Profiles already-acquired public datasets (UCI Default of Credit Card Clients, South German Credit, BCB SGS), kept strictly separate from any synthetic build. |
| `credlens.analysis.charts` | 12 chart functions, Okabe-Ito colorblind-accessible palette, a "Synthetic data" watermark on every figure, PNG output. Pure rendering over already-fetched DataFrames - no querying. |
| `credlens.analysis.provenance` | The analysis manifest - build identity, source hashes, versions, every query/table/figure produced and its content hash, parameters, warnings, final status. |
| `credlens.analysis.reporting` | Builds the bilingual executive summary ("decision cards": question / evidence / interpretation / decision it could support / risk-limitation) and technical report - pure string formatting from DataFrames/dicts a run itself computed, never a hand-typed number. |
| `credlens.analysis.runner` | Orchestrates all of the above into one `run_analysis()` call, writing the full output tree. |

## SQL-first discipline

Every number in a report traces back to one of two places: an existing, dbt-tested mart under `warehouse/models/marts/`, or a documented ad hoc SQL query inside `metrics.py`/`scenarios.py` (purpose, grain, filters, null handling, all in a docstring directly above the query). `credlens.analysis` never recomputes a KPI in pandas that the warehouse already computes in SQL - `pandas` here is used to hold a query's *result*, format a report, or drive a chart, never to reimplement business logic. See `analysis/README.md` for why there is no separate `analysis/queries/*.sql` directory (it would just be an unmaintained, unexecuted copy of the same SQL).

## Segmentation and the minimum-sample rule

`MIN_SEGMENT_OBSERVATIONS = 10` (`metrics.py`) - every segmented breakdown (funnel by channel, portfolio by region × channel, approval rate by policy version, composition-vs-performance's shared/marginal groups) adds a `low_sample: bool` column rather than dropping small cells, so coverage stays visible even where a rate should not be quoted as a headline finding. Full rationale and the permitted segmentation attributes: `analysis/specifications/segmentation_policy.md`.

## Scenario pairing: composition vs. performance

`policy_expansion`/`policy_tightening` share the exact same `application_id` population as `baseline` (common random numbers - see `docs/common_random_numbers.md`), so "did the policy help or hurt" can be answered two genuinely different ways that must never be conflated:

1. **Mechanical/composition effect** - how many additional/fewer applications got booked (`baseline_only_count`, `scenario_only_count`).
2. **Performance effect** - among applications booked in **both** runs (the shared population), did their outcome (PAR90, outstanding balance) differ? This isolates whether the scenario changed underwriting decisions on the margin from whether it changed how the *same* contracts perform - a real difference here would indicate a CRN bug, not a policy effect, since payment-behavior config is identical across policy scenarios.

Matched by `application_id`, never `contract_id` - contract ids are assigned in scenario-specific order among approved applications, so the same underlying application can get a *different* `contract_id` string in baseline vs. a policy scenario even though `application_id` is identical.

## Multi-seed robustness

A single seed cannot characterize how stable a scenario's effect is. `multiseed.robustness_across_seeds(scenario, scale_name, n_seeds, start_seed)` runs `n_seeds` real generations (default `start_seed=970_001`, chosen to never collide with an official demonstration run/suite - Phase 6 gate B) and reports mean/stdev/min/max delta and the fraction of seeds where the effect moved in the expected direction. The result is explicitly labeled `"simulation_variability_across_synthetic_dgp_seeds"` in every output (`RobustnessSummary.to_dict()`, the technical report's own section) - never "confidence interval." This performs real data generation, so it is **opt-in** (`credlens analysis run --multiseed`) and never run in CI (see `.github/workflows/ci.yml`'s own comment on this).

## Public benchmark appendix

`benchmark.profile_public_sources()` profiles whatever already-acquired public datasets it finds (UCI Default of Credit Card Clients - Taiwan, 2005; South German Credit - Germany, 1973-1975; BCB SGS macro series - Brazil, aggregate banking system), reusing `credlens.data.audit.audit_dataframe` (Phase 2) rather than reimplementing structural profiling. It degrades to an empty list - never an error - if the manifest or files are absent (e.g. in CI, where `data/raw/` is gitignored and never fetched). Every consumer keeps this appendix visually and numerically separate from the synthetic operational analysis, and never claims population equivalence between a public source and CredLens's own synthetic Brazilian fintech.

## Provenance manifest

`reports/portfolio_analysis/manifest.json` (`provenance.AnalysisManifest`) records: analysis id, build id, warehouse fingerprint, suite id, run ids, per-source content hashes, generator/contract/package/dbt/DuckDB/Python versions, every query executed, every table/figure written and its own sha256 content hash, the exact `run_analysis()` parameters used (so `credlens analysis reproduce` can replay an identical invocation), warnings, and final status. `validate_build_for_analysis()` refuses a nonexistent build, a build with failed tests, a build with tampered sources, or a build missing its fingerprint - the analysis layer never trusts a build's own manifest blindly, even though `credlens warehouse build` already checked most of this once.

## The `credlens analysis` CLI

| Command | Purpose |
|---|---|
| `credlens analysis validate --build-id` | Re-checks a build is safe to analyze, without running the full analysis. |
| `credlens analysis run --build-id [--output-dir] [--force] [--no-benchmark] [--multiseed ...]` | Runs the full analysis, writing tables/figures/bilingual reports/manifest. Refuses to silently overwrite an existing output directory without `--force`. |
| `credlens analysis scenarios --build-id` | Paired scenario comparison and composition-vs-performance, without writing the full report tree - a quick look. |
| `credlens analysis benchmark` | Profiles the public benchmark sources, standalone. |
| `credlens analysis status --output-dir [--analysis-id]` | Reads back a prior run's manifest. |
| `credlens analysis reproduce --output-dir [--reproduce-dir]` | Re-runs the same `build_id` (with the same recorded parameters) into a separate directory and verifies every table/figure content hash matches exactly - the reproducibility proof, automated (`tests/test_analysis_runner.py::TestRunAnalysisIsReproducible` runs the equivalent check directly against `run_analysis()`). |

Every subcommand supports `--json` for machine-readable output and returns a proper process exit code (0 success, 1 failure) - never silent.

## Output tree

```
reports/portfolio_analysis/
├── README.md
├── manifest.json
├── executive_summary.md / executive_summary.pt-BR.md
├── technical_report.md / technical_report.pt-BR.md
├── tables/*.csv       # one per named query
└── figures/*.png      # one per chart function
```

`notebooks/credit_portfolio_case_study.ipynb` is a thin, read-only viewer over this exact tree - it loads the CSVs/PNGs and narrates them, it never recomputes a query or duplicates logic that lives in this package (see the notebook's own first cell).

## Running it

```bash
uv sync --extra warehouse --extra analysis
uv run credlens warehouse build --suite-id SUITE_sample_2026
uv run credlens analysis validate --build-id <build_id>
uv run credlens analysis run --build-id <build_id>              # writes reports/portfolio_analysis/
uv run credlens analysis run --build-id <build_id> --multiseed  # + a real multi-seed sweep (slower)
uv run credlens analysis reproduce --output-dir reports/portfolio_analysis
```

## Limitations

- Requires a **suite** build (baseline + every CRN scenario), not a single run - `run_analysis()` raises `AnalysisRunError` otherwise, since there is nothing to compare.
- `--multiseed` performs real data generation and is comparatively slow - never run repeatedly at portfolio scale (Phase 6 section 13).
- The notebook's execution could not be verified with a real Jupyter kernel in this environment (no `nbconvert`/`ipykernel` installed - a deliberate choice, see `analysis/README.md` and `pyproject.toml`'s `analysis` extra comment); its code cells were verified to execute correctly against real output with `IPython.display` stubbed out, which is not equivalent to a genuine kernel execution. See the Phase 6 final report for the exact verification performed.
- No revenue/cost/LGD/EAD/regulatory-PD data exists anywhere in this layer's output - see `docs/warehouse_architecture.md`'s own Limitations section, which this layer inherits unchanged.
