[Leia em português (pt-BR)](README.pt-BR.md)

# CredLens — Credit Risk & Portfolio Analytics

**CredLens turns a digital lender's credit portfolio into a reproducible, tested analytics product — from business question to KPI to decision.**

**Status: Foundation phase.** This repository currently contains business framing, architecture, and project scaffolding only. No data has been acquired, no model has been trained, no dashboard exists, and no metric below has been calculated. Every number you might expect to see here (portfolio size, delinquency, ROI, accuracy) is deliberately absent — see [Current capabilities](#current-capabilities) and [`docs/roadmap.md`](docs/roadmap.md) for what happens next.

## The business scenario

CredLens is built around a fictional digital credit company that originates unsecured consumer loans. Like any lender, it has to manage tension between four levers at once: **how many applicants to approve, how much risk to carry, how much to charge, and how much to recover when payments slip.** Optimizing any one lever in isolation (e.g., approving more people) tends to damage another (e.g., delinquency). The company's leadership needs a shared, defensible view of the portfolio to make that trade-off deliberately instead of by accident.

The central executive question this project is organized around:

> **How do we grow or protect credit portfolio profitability while balancing approval, delinquency, expected loss, and recovery?**

Full context — situation, symptoms, executive questions, and the diagnostic tree connecting them — is in [`docs/business_problem.md`](docs/business_problem.md). None of it is presented as answered yet; see that document's explicit separation of description, diagnosis, forecast, and decision.

## Questions this project will eventually help answer

- Is delinquency rising because of new customers, specific vintages, or a shift in portfolio mix?
- Which segments concentrate the most exposure and loss?
- Is higher approval actually producing *profitable* growth, or just more volume?
- Which loan vintages are deteriorating fastest, and how fast?
- How do customers move between "current" and different delinquency buckets over time?
- How effective are the collections strategies in use?
- If the approval cutoff moved, what would happen to approval volume, risk, and expected result?
- What should leadership track daily, monthly, and by vintage?

These are stated and structured now (see [`docs/business_problem.md`](docs/business_problem.md) and [`docs/kpi_dictionary.md`](docs/kpi_dictionary.md)); they are **not** answered in this phase.

## Planned analytical products

Once later phases land, this project is scoped to produce:

- A **KPI dictionary and semantic layer** covering origination, portfolio, delinquency, vintage, recovery, and profitability metrics — each with an explicit formula, grain, and owner (draft: [`docs/kpi_dictionary.md`](docs/kpi_dictionary.md)).
- A **SQL/dbt-modeled warehouse** (DuckDB for local development) with tested, documented dimensional models.
- **Portfolio and vintage analysis** — growth, mix shift, delinquency roll rates, cure rates — built on top of that warehouse.
- An **interpretable credit risk model** and a **policy simulator** to estimate the effect of cutoff changes before they're made.
- A **Power BI dashboard** and a lightweight demo application for stakeholder-facing exploration.

None of these exist yet. They are scoped, not built — see [`docs/roadmap.md`](docs/roadmap.md).

## Architecture (summary)

```mermaid
flowchart LR
    A[Public + synthetic data sources] --> B[Ingestion]
    B --> C[Data quality checks]
    C --> D[Transformation / dbt models]
    D --> E[SQL warehouse - DuckDB]
    E --> F[Analytics layer - KPIs, vintages, risk]
    F --> G[Presentation - Power BI, demo app]
```

This is the target architecture for the full project, not what is implemented today. Layer responsibilities, technology rationale, and what's implemented vs. planned are documented in [`docs/architecture.md`](docs/architecture.md).

## Current capabilities

What exists in the repository right now:

- Project scaffolding: source layout, dependency management, lint/type/test configuration.
- A minimal, tested CLI (`credlens --help`, `credlens version`, `credlens doctor`) that verifies the *installation*, not the business logic.
- Centralized configuration loading (`config/base.yaml`) with validation and clear error messages.
- Structured logging setup.
- Business documentation: charter, business problem framing, stakeholder map, KPI dictionary (definitions only, no computed values), data strategy, architecture, assumptions & limitations, glossary, roadmap.
- CI (GitHub Actions): lint, format check, type check, tests with coverage — on every push.

## Planned capabilities (not yet implemented)

- Data acquisition and licensing audit for candidate public datasets.
- A reproducible synthetic operational data layer.
- Dimensional data modeling and dbt transformations.
- A queryable SQL warehouse (DuckDB, optionally Postgres).
- Data quality validation (Pandera or equivalent).
- Portfolio, vintage, and roll-rate analysis.
- An interpretable probability-of-default model and expected-loss calculation.
- A cutoff/policy simulator.
- A Power BI dashboard and a demo application.
- Containerization and an expanded CI/CD pipeline.

See [`docs/roadmap.md`](docs/roadmap.md) for the full phase sequence and dependencies between phases.

## Quick start

Requires Python 3.11+ and, ideally, [`uv`](https://docs.astral.sh/uv/).

```bash
git clone <this-repository>
cd credlens-credit-analytics

# Install (uv resolves and locks dependencies automatically)
uv sync --all-groups

# Verify the installation
uv run credlens --help
uv run credlens version
uv run credlens doctor
```

Without `uv`, use a standard virtual environment instead:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
credlens --help
```

> Note: `pip install -e ".[dev]"` requires `dev` to be declared as an optional dependency group. This project defines its dev dependencies under `[dependency-groups]` (PEP 735) for `uv`; if you install with plain `pip`, install the packages listed under `dependency-groups.dev` in `pyproject.toml` individually (`pip install pytest pytest-cov ruff mypy types-PyYAML`).

## Development commands

A `Makefile` is provided for convenience. Every target has a documented `uv run` equivalent for contributors who don't use `make`.

| Task | Make | Direct (uv) |
|---|---|---|
| Install deps | `make install` | `uv sync --all-groups` |
| Lint | `make lint` | `uv run ruff check .` |
| Format check | `make format-check` | `uv run ruff format --check .` |
| Format (write) | `make format` | `uv run ruff format .` |
| Type check | `make typecheck` | `uv run mypy src tests` |
| Tests | `make test` | `uv run pytest` |
| Tests + coverage | `make coverage` | `uv run pytest --cov=credlens --cov-report=term-missing` |
| Run CLI | `make run ARGS="doctor"` | `uv run credlens doctor` |
| Everything CI runs | `make ci` | see `.github/workflows/ci.yml` |

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full contributor workflow.

## Tests

```bash
uv run pytest
```

Foundation-phase tests cover: package import and version exposure, CLI help/version/doctor commands, and configuration loading (including missing-file, invalid-YAML, and schema-validation error paths). Coverage is measured on the code that exists in this phase (`src/credlens`) — it is not a proxy for how much of the eventual product is finished.

## Repository structure

```text
credlens-credit-analytics/
├── README.md / README.pt-BR.md   # This file, and its Portuguese counterpart
├── pyproject.toml                # Package metadata, dependencies, tool config
├── config/                       # base.yaml - structural configuration (no secrets)
├── data/                         # Empty by design in this phase (see data/README.md)
├── docs/                         # Business and architecture documentation
├── src/credlens/                 # Application package (CLI, config, logging)
├── tests/                        # Pytest suite
└── .github/                      # CI workflow and issue/PR templates
```

## Data strategy (summary)

The target strategy is **public data + a reproducible synthetic operational layer**: real, licensed public credit/macroeconomic datasets provide realistic structure and distributions; a documented, code-generated synthetic layer fills in the operational detail (e.g., day-to-day delinquency transitions) that public datasets don't expose, without ever presenting synthetic values as real observed outcomes. Candidate sources, licensing status, and the synthetic/public labeling approach are tracked in [`docs/data_strategy.md`](docs/data_strategy.md). No dataset has been downloaded in this phase.

## Limitations

This is a portfolio project about a **fictional** company. It contains no real customers, no real personal or financial data, and (in this phase) no computed business results. It cannot be used to make real credit decisions, and any future model or metric it produces will require independent statistical, legal, and regulatory validation before any real-world use. See [`docs/assumptions_and_limitations.md`](docs/assumptions_and_limitations.md) for the full list.

## Roadmap

See [`docs/roadmap.md`](docs/roadmap.md) for the phased plan, from this foundation through data acquisition, modeling, analytics, risk scoring, policy simulation, dashboards, and publication readiness.

## License

Code is licensed under [MIT](LICENSE). Any third-party dataset used in future phases remains subject to its own license — see [`docs/data_strategy.md`](docs/data_strategy.md).

---

[Leia em português (pt-BR)](README.pt-BR.md)
