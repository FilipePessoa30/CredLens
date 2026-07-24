# Changelog

All notable changes to this project are documented in this file. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.0] - 2026-07-24

### Added — Conceptual modeling, temporal semantics, and data contracts phase

- Conceptual data model: 17 entities (customers, applications, application_features, fairness_attributes, policy_versions, credit_decisions, contracts, installments, payments, payment_allocations, account_monthly_snapshots, collection_events, write_off_events, recovery_events, macro_context_monthly, generation_runs) plus a specified-but-not-built "synthetic truth" layer, modeled as a hybrid of events, current state, and snapshots (never one undifferentiated table) across 4 Mermaid ER diagrams. See `docs/conceptual_data_model.md`.
- `docs/temporal_semantics.md`: formal roles for every timestamp/date family (`event_timestamp`, `effective_from`/`effective_to`, `snapshot_date`, `due_date`, `payment_date`, `settlement_date`, `write_off_date`, `as_of_date`, `ingested_at`, `generated_at`), a causal ordering chain, and documented valid exceptions.
- `docs/state_machines.md`: reviewed (not blindly accepted) state machines for applications, contracts, and installments, with an explicit table of what is/isn't mechanically enforced.
- `docs/metric_semantics.md`: a project-specific (not regulatory) DPD bucket convention, and an explicitly *unconfigured* "Default" definition (threshold/window/write-off treatment all left `unset`, versioned for a future phase to actually decide).
- `src/credlens/contracts` package: `models` (Pydantic schema for contract YAML metadata), `loader`, `registry` (cross-reference validation, known-business-rule-code registry), `validators` (audit/strict dispatch, single-file and scenario-directory modes), `domain_rules` (vectorized PK/FK/domain/nullability/CPF-pattern checks), `relational_rules`/`temporal_rules`/`financial_rules` (22 named, vectorized, cross-table business rules), `reporting` (`Finding`/`ValidationReport`, stable error codes).
- 20 data contracts: `contracts/raw/*.yaml` (4, covering the Phase 2 public sources) and `contracts/operational/*.yaml` (16, covering the not-yet-built synthetic operational layer) - each with grain, PK, FKs, typed/domain-constrained columns, uniqueness rules, and named business rules.
- Two validation modes on `credlens contracts validate`: `audit` (diagnostic, never fails the command - for the immutable public sources) and `strict` (fails on any error finding - for the future synthetic layer and its test fixtures). See `docs/adr/0006-audit-vs-strict-validation.md`.
- Automated the two pieces of Phase 2 technical debt this phase was required to close: UCI EDUCATION/MARRIAGE out-of-domain code detection (previously a one-off manual script; now the `uci_default_credit` contract's declared domains, reproducing the same 345/54 violation counts) and BCB observation-date uniqueness/ordering (previously a manual re-check after the chunking-boundary bug fix; now the `data` primary key plus the `bcb_dates_strictly_increasing` business rule) - both with permanent regression tests.
- `docs/synthetic_generation_spec.md` and `config/synthetic/*.blueprint.yaml` (6 named scenarios: baseline, policy_expansion, policy_tightening, macroeconomic_stress, collections_change, data_quality_incident) - a specification and structurally-validated blueprints only, with every parameter honestly marked `pending`/`requires_calibration` (never a fabricated real-world value) and a "known truth" section for a future generator's own validation. No synthetic data is generated.
- CLI additions, all existing commands preserved: `credlens contracts list|show|validate`, `credlens synthetic plan|scenarios|validate-blueprints`, and `credlens synthetic generate` (which deliberately prints "Not implemented: scheduled for the synthetic generation phase." and exits 1 - no data is produced).
- 7 ADRs (`docs/adr/0001`-`0007`): foreign-vs-Brazilian-context separation, adoption of a synthetic operational layer, hybrid events/state/snapshots architecture, feature freeze at the proposal instant, fairness-attribute physical separation, audit-vs-strict validation modes, and synthetic-truth isolation.
- `tests/fixtures/contracts/`: one small, coherent `valid_minimal_scenario` (passes all 16 operational contracts in strict mode with zero findings) plus 11 purpose-built invalid scenarios (PK duplicate, FK orphan, invalid domain, causally impossible date, approval without a valid policy, contract from a rejected application, payment exceeding its allocation, cross-contract allocation, incompatible DPD/bucket, duplicate snapshot, recovery before write-off) - each verified to fail with its exact intended finding code.
- 228 new tests (369 total) covering the contracts package (models/loader/registry/validators/domain_rules/relational_rules/temporal_rules/financial_rules/reporting), `credlens.synthetic`, both new CLI command groups, the full fixture suite end-to-end, and dedicated regressions for the EDUCATION/MARRIAGE automation, BCB date uniqueness/chunking, the timezone-comparison bug found and fixed this phase, and CPF-shaped identifier detection.
- New dependency: `pydantic` (contract/blueprint metadata parsing only - table data validation stays vectorized pandas, never per-row). See `docs/adr/0006-audit-vs-strict-validation.md` and the rationale comment in `pyproject.toml`.
- 4 real bugs found and fixed during this phase's own construction, documented transparently in `docs/data_contracts.md`: a timezone-naive/aware comparison crash, a type-mismatch false positive on `macro_context_monthly.series_code`, a missing foreign-key data check, and a synthetic-truth field that had been misplaced directly on an operational table (caught before merge, not after).

### Explicitly not included in this phase

No synthetic data generation (the generator, blueprints' calibration, and `credlens synthetic generate`'s actual implementation are explicitly deferred), no dbt models, no SQL warehouse, no KPI computation, no risk model, no policy simulator, no dashboard, no changes to any raw file under `data/raw/`, and no commits or pushes. See `docs/roadmap.md` for what each of these becomes in later phases.

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
