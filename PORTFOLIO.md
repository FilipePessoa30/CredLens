# CredLens — Portfolio Summary

*A 2-minute read. For the full technical detail, see [README.md](README.md); for a one-page recruiter view, see [docs/recruiter_brief.md](docs/recruiter_brief.md); for interview-ready answers, see [docs/interview_guide.md](docs/interview_guide.md). Versão em português: [PORTFOLIO.pt-BR.md](PORTFOLIO.pt-BR.md).*

## The problem

Credit portfolio management involves risk, credit, collections, finance, and product teams that each see a slice of the same portfolio through different tools and definitions — producing metric disagreement and slow, ad hoc answers to questions like "which vintage is deteriorating?" CredLens is a portfolio project (not a real company or real data) built to demonstrate how a single, versioned, tested analytics + modeling + monitoring stack solves that problem end to end.

## Stakeholders

Executive leadership, risk management, credit/underwriting, collections, finance, product, operations, data & technology, and audit/governance — see `docs/stakeholder_map.md`. Each has a distinct decision the product is designed to eventually support (approval cutoffs, collections prioritization, growth-vs-loss trade-offs).

## Data

Two data sources, used for two different, explicitly-labeled purposes, never blended:
- **A synthetic, generated portfolio** (`credlens.generation`) — origination-to-collections lifecycle events for a fictional lender, built from a documented, seeded, reproducible data-generating process (DGP). Powers the Executive Overview, Credit Funnel, Portfolio & Delinquency, Vintages, Cure/Collections, and Scenario Lab dashboard pages.
- **The UCI "Default of Credit Card Clients" benchmark** (real, historical, Taiwan, 2005, publicly licensed) — powers the behavioral early-warning model, its independent validation, and the monitoring simulation. Never mixed with the synthetic portfolio's numbers.

## Architecture

```
Synthetic DGP ──┐                    UCI benchmark ──┐
                 ├─► DuckDB (dbt) ──► Analysis ──┐    ├─► Modeling ──► Independent  ──► Monitoring
                 │   (staging→marts)  (Python)   │    │   (sklearn)    validation       simulation
                 │                               ▼    │                (recompute,       (drift,
                 └───────────────────────► Streamlit dashboard (10 pages) ◄┘                alerts,
                                                                                             incidents)
```

- **SQL modeling**: 64 dbt models (raw → staging → intermediate → dimensions → facts → marts), 135+ generic and singular dbt tests, running on DuckDB.
- **Independent reconciliation**: every KPI computed by dbt/SQL is re-derived by an independent Python implementation and compared within a documented tolerance — never "trust the query," always "prove the query."
- **Modeling**: an 18-feature interpretable logistic regression (behavioral early-warning default model) plus a HistGradientBoosting challenger, full leakage controls, calibration, subgroup diagnostics, and robustness perturbations.
- **Independent model validation**: a *separate* package (`credlens.model_validation`) that never copies the model's own reported numbers — it recomputes discrimination/calibration from frozen predictions and runs two independent negative-control permutation tests.
- **Monitoring simulation**: a simulated batch-scoring stream over the model's own locked test set, with calibrated drift/performance thresholds and a signal → alert → incident escalation hierarchy.
- **Dashboard**: 10 Streamlit pages, each independently AppTest-covered and, this release, verified with a real headless browser (screenshots, console-error check).

## Key, real, measured results

- 1,599 automated tests, 94% statement coverage, strict `mypy`, `ruff` lint + format clean, all in CI.
- Behavioral model: ROC-AUC 0.745 / PR-AUC 0.502 on a frozen, never-retrained-on test holdout; independently re-validated with two permutation controls (999 + 100 resamples) at α=0.01.
- **A genuine methodological fix, not a rerun**: this release's audit of the original permutation test found and corrected a real multiple-comparisons problem in monitoring (a naive per-feature threshold produced a ~60% false-alert rate across 100 genuinely normal batches; a family-wise-calibrated threshold brought it to ~4%/1%), and a real optimism bias in the performance reference (train+validation overstated true holdout ROC-AUC by ~0.012).
- A remediated, 11-feature logistic regression was built and independently registered (`remediation_candidate`) after discovering a second, previously-masked collinearity — corroborated two different ways — while the original model was left untouched.
- Real headless-browser visual QA of all 10 dashboard pages found and fixed one real regression before this write-up (a default-selection bug that would have shown an all-zero Model Lab overview to a first-time visitor).

## Limitations (stated plainly)

Historical, non-Brazilian benchmark; synthetic portfolio for the analytics layers; no fairness certification; no real-money claim; the modeling holdout has been repeatedly (though never re-fit) observed across phases — disclosed, not hidden. Full list: `docs/assumptions_and_limitations.md` and the release manifest's `known_limitations`.

## Reproduce it

```bash
uv sync --all-groups --extra warehouse --extra analysis --extra dashboard --extra notebook --extra modeling
uv run pytest -m "not slow"          # fast suite
uv run credlens dashboard run --demo # explore all 10 pages, no build required
```

Full quick start, CLI reference, and every report referenced above: [README.md](README.md).
