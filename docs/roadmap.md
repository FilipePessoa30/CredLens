# Roadmap

An incremental phase plan. No phase beyond Phase 1 is implemented. Each phase lists its dependency on prior phases and the criteria that would mark it complete — no dates are assigned, since forcing arbitrary deadlines onto a portfolio project would be as fabricated as an invented metric.

| # | Phase | Depends on | Completion criteria |
|---|---|---|---|
| 1 | **Foundation** | — | Package installs; CLI (`--help`, `version`, `doctor`) works; config loads and validates; tests, lint, and type checks pass; CI runs them on every push; business/architecture docs exist and make no unearned claims. *(Complete.)* |
| 2 | **Data acquisition and audit** | 1 | Candidate dataset(s) selected from `docs/data_strategy.md`; license and leakage risks reviewed and documented; data downloaded into `data/raw/` (git-ignored) via a reproducible CLI (`credlens data fetch`); structural audit (row counts, schema, quality findings) documented. *(Complete: 4 of 5 registered sources acquired and audited — uci-default-credit, south-german-credit, bcb-sgs-20570, bcb-sgs-21112; home-credit blocked with documented evidence. See `docs/dataset_selection.md`, `docs/data_quality_audit.md`, `docs/target_and_leakage_audit.md`, `docs/sensitive_attributes.md`.)* |
| 3 | **Conceptual and dimensional modeling** | 2 | Entity/fact/dimension model documented (e.g., an ERD) for the portfolio domain (applications, loans, payments, delinquency snapshots); grain of every planned table stated explicitly. |
| 4 | **Ingestion and ETL** | 2, 3 | Ingestion code loads raw sources into the warehouse's staging layer, reproducibly and idempotently; synthetic data generator (if used) implemented and documented per `docs/data_strategy.md`. |
| 5 | **Data quality** | 4 | Automated validation (e.g., Pandera) checks schema, types, ranges, and referential integrity on staging data; failures block downstream transformation rather than passing silently. |
| 6 | **Warehouse and SQL modeling** | 3, 4, 5 | dbt models transform staging into tested, documented marts in DuckDB; each model has at least basic dbt tests (uniqueness, not-null, relationships where applicable). |
| 7 | **Portfolio analysis** | 6 | KPIs in `docs/kpi_dictionary.md` computed from the warehouse (not ad hoc scripts); each computed KPI's status updated from `proposed`/`requires_validation` to reflect that it has now been implemented and reviewed. |
| 8 | **Vintages and transitions** | 6, 7 | Vintage delinquency curves and roll-rate/cure-rate transition matrices computed and validated against the dimensional model's grain. |
| 9 | **Profitability and expected loss** | 6, 7 | Revenue, cost of funds, contribution margin, and a first expected-loss calculation (PD × EAD × LGD, using whatever proxy/benchmark approach is chosen and documented) implemented, with every modeling assumption stated. |
| 10 | **Interpretable risk model** | 7, 9 | A PD (or equivalent) model trained on the warehouse's modeled data, documented with its features, validation approach, and known limitations; interpretability prioritized over raw performance where the two trade off. |
| 11 | **Policy simulator** | 10 | A tool (script or app) that estimates the effect of moving the approval cutoff on approval volume, portfolio risk, and expected result, explicit that its output is a model-based estimate under stated assumptions, not a causal guarantee (per `docs/assumptions_and_limitations.md`). |
| 12 | **Power BI** | 7, 8, 9 | A dashboard connected to the warehouse (or an extract of it) presenting KPIs, vintages, and profitability views to the stakeholders identified in `docs/stakeholder_map.md`. |
| 13 | **Demonstration application** | 11 | A lightweight app (e.g., Streamlit) exposing the policy simulator interactively, for reviewers who can't open Power BI. |
| 14 | **Integration testing** | 4-13 (whichever exist) | End-to-end tests that exercise the pipeline from raw data through to a KPI or model output, catching regressions across phases. |
| 15 | **Docker and expanded CI/CD** | 14 | The project (or its demo app) containerized for reproducible execution; CI expanded to cover data/model checks introduced by later phases. |
| 16 | **Executive documentation** | 7-13 (whichever exist) | A stakeholder-facing summary translating the technical build into the business narrative from `docs/business_problem.md`, honestly scoped to what was actually built. |
| 17 | **Publication readiness** | all above | Final README pass, licensing check on any included data artifacts, repository cleanup, and a last check that no phase's documentation overstates what phases 1-16 actually produced. |

## How this roadmap is meant to be used

- A phase does not start until its dependencies are marked complete against the criteria above — not against a subjective sense of "good enough."
- Completing a phase means updating this table's row (and any linked documents) to reflect reality, not marking it done in advance of the work.
- Phases 7 onward will very likely surface the need for the "requires_validation" KPIs in `docs/kpi_dictionary.md` to be revised. That is expected and welcome — the dictionary is preliminary by design.
