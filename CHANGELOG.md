# Changelog

All notable changes to this project are documented in this file. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-07-23

### Added — Foundation phase

- Project scaffolding: `src`-layout Python package (`credlens`), `pyproject.toml` with dependency, lint, type-check, and test configuration, and a `uv.lock` reproducible lockfile.
- Minimal CLI (`credlens` / `python -m credlens`) with `--help`, `version`, and `doctor` commands, the last verifying only foundation-phase concerns (Python version, package version, config file, required directories) and explicitly not treating an absent dataset as a failure.
- Centralized configuration loading and validation (`credlens.config`) reading `config/base.yaml`, with clear errors for missing files, invalid YAML, and schema violations.
- Structured logging setup (`credlens.logging_config`).
- Pytest suite covering package import/version, all three CLI commands (including the `python -m credlens` entry point), and configuration loading's success and error paths.
- Ruff (lint + format), MyPy (strict), and Pytest-cov wired into local development and GitHub Actions CI.
- Business and architecture documentation: project charter, business problem framing, stakeholder map, preliminary KPI dictionary, data strategy, target architecture, assumptions & limitations, glossary, and phased roadmap.
- `README.md` and `README.pt-BR.md`, `LICENSE` (MIT), `CONTRIBUTING.md`, `SECURITY.md`, and GitHub issue/PR templates.

### Explicitly not included in this phase

No data acquisition, no ETL, no SQL warehouse, no dbt models, no exploratory analysis, no computed KPI values, no risk model, no policy simulator, no Power BI dashboard, no demo application, no Docker, and no claimed business results. See `docs/roadmap.md` for what each of these becomes in later phases.
