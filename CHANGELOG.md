# Changelog

All notable changes to this project are documented in this file. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - 2026-07-23

### Added — Data acquisition, provenance, and audit phase

- `credlens.data` package: `models` (typed source/manifest/download records), `registry` (loads/validates `data/metadata/source_registry.yaml`, checks status-evidence coherence), `downloader` (idempotent HTTP acquisition with retries, atomic writes, path-traversal protection, safe zip extraction), `bcb_client` (Banco Central do Brasil SGS time-series client with explicit date ranges and window chunking), `checksums` (SHA-256), `manifest` (deterministic `data/metadata/file_manifest.csv` read/write/verify), `schema` (documented-column comparison), `profiler` (structural DataFrame profiling), `audit` (categorized findings: confirmed problem / candidate anomaly / documented characteristic / hypothesis requiring investigation / structural limitation).
- CLI: `credlens data sources`, `credlens data fetch --source <id>`, `credlens data verify`, `credlens data audit`; `credlens doctor` now reports registered data-source counts as an informational check.
- Real, reproducible acquisition of 4 of 5 registered sources this session: `uci-default-credit` (Default of Credit Card Clients, UCI, CC BY 4.0), `south-german-credit` (South German Credit, UCI, CC BY 4.0), `bcb-sgs-20570` and `bcb-sgs-21112` (Banco Central do Brasil SGS series, ODbL). `home-credit` (Kaggle) registered as `BLOCKED_REQUIRES_USER_ACCESS` with documented evidence, per this project's rule against embedding or requesting credentials.
- A real bug caught by this project's own audit tooling and fixed during acquisition: BCB SGS date-window chunking produced one duplicate observation per series at a chunk boundary (month-inclusive date semantics); fixed in `credlens.data.bcb_client` with a targeted, order-preserving deduplication that only removes byte-for-byte identical repeats.
- New documentation: `docs/dataset_selection.md` (weighted decision matrix + sensitivity analysis), `docs/data_sources.md`, `docs/data_licensing.md`, `docs/data_dictionary.md`, `docs/data_quality_audit.md`, `docs/target_and_leakage_audit.md`, `docs/sensitive_attributes.md`.
- New dependencies: `requests` (HTTP), `pandas` (tabular reading + audit statistics), dev-only `responses` (HTTP mocking in tests) and `pandas-stubs`/`types-requests` (mypy strict compliance).
- `config/base.yaml` gained an optional `data:` section (HTTP timeout/retries, BCB query defaults) - purely structural, no credentials, no business thresholds.
- 76 new tests (141 total) covering the full data-acquisition layer, including HTTP-mocked downloader/BCB-client edge cases (timeouts, retries, 4xx/5xx, partial-file safety, overwrite protection, path traversal), manifest determinism, schema/profiler/audit logic, and CLI end-to-end flows sandboxed away from real files.

### Explicitly not included in this phase

No analytical cleaning or transformation of raw data, no dimensional modeling, no SQL warehouse, no synthetic data generation, no model training, no PD/score calculation, no policy simulation, no dashboard, and no commits or pushes. See `docs/roadmap.md` for what each of these becomes in later phases.

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
