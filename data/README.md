# data/

This directory holds acquired raw data (git-ignored) and its provenance metadata (versioned). See `docs/data_sources.md` for what's here and how it was acquired, and `docs/data_licensing.md` for licenses.

## Current structure

```text
data/
├── README.md                # this file (versioned)
├── raw/                      # Acquired, unmodified source files (git-ignored)
│   ├── uci_default_credit/   # Default of Credit Card Clients (CSV)
│   ├── south_german_credit/  # South German Credit (extracted ZIP contents)
│   ├── home_credit/          # Empty - BLOCKED_REQUIRES_USER_ACCESS, see docs/data_licensing.md
│   └── bcb_sgs/               # BCB SGS series 20570 and 21112 (JSON)
├── external/                  # Reserved for future external reference data (git-ignored, empty)
├── interim/                   # Reserved for a future transformation phase (git-ignored, empty)
├── processed/                  # Reserved for a future transformation phase (git-ignored, empty)
├── synthetic/                  # Generated portfolios (Phase 4A, git-ignored) - see docs/synthetic_generation_implementation.md
│   └── <generation_run_id>/    # operational/*.parquet, manifest.json, config_snapshot.yaml, contract_validation.json, generation_summary.json
├── synthetic_truth/             # The isolated synthetic-truth layer (Phase 4A, git-ignored) - never merged with synthetic/
│   └── <generation_run_id>/    # latent_customer_truth.parquet, latent_contract_truth.parquet, truth_manifest.json
└── metadata/                   # Provenance records - versioned, contains NO data content
    ├── source_registry.yaml    # What each source is, its license, its lifecycle status
    ├── dataset_roles.yaml      # Why each source has its role (short version of docs/dataset_selection.md)
    ├── file_manifest.csv       # Every acquired file: path, size, SHA-256, retrieval time, row/col counts
    ├── schemas/                 # Documented column lists per source (used to detect drift)
    └── licenses/                 # License text and verification evidence per source
```

`interim/` and `processed/` remain genuinely empty in this phase - no transformation has happened yet (see `docs/roadmap.md`, phases 3-6). `external/` remains empty - no additional reference data was needed beyond the five registered sources. `synthetic/` and `synthetic_truth/` are empty on a fresh clone - run `uv run credlens synthetic generate --scenario baseline --scale smoke --seed <N>` to populate them.

## What's versioned vs. git-ignored

- **Versioned**: this file, and everything under `data/metadata/` (YAML/CSV/Markdown provenance records - never the data itself).
- **Git-ignored**: everything under `data/raw/`, `data/external/`, `data/interim/`, `data/processed/`, `data/synthetic/`, `data/synthetic_truth/`. Verified with `git check-ignore -v` (Phase 2 final report) and `git status --ignored` (Phase 4A final report).

This means a fresh clone of this repository has `data/metadata/` populated but `data/raw/` empty. That's intentional and reproducible: run `uv run credlens data fetch --source <id>` for each source listed in `data/metadata/source_registry.yaml` to repopulate it (see `docs/data_sources.md` for exact commands), then `uv run credlens data verify` and `uv run credlens data audit` to reproduce this session's checksums and audit findings.

## Rules that apply here

- Nothing under `data/raw/`, `data/external/`, `data/interim/`, `data/processed/`, `data/synthetic/`, or `data/synthetic_truth/` is ever committed to git.
- Every acquired file's license is recorded in `data/metadata/source_registry.yaml` and `docs/data_licensing.md` before acquisition, not after.
- Synthetic data (`data/synthetic/`, `baseline` scenario only as of Phase 4A - see `docs/synthetic_generation_implementation.md`) is mechanically distinguishable from public data by construction: it lives under a different top-level directory, every row is marked `is_synthetic=true` where the schema carries that column (e.g. `generation_runs`, `macro_context_monthly`), and the two are never joined or blended by any command in this repository.
- The synthetic-truth layer (`data/synthetic_truth/`) is physically separate from `data/synthetic/`, never read by the decision-scoring code, and never used as a model feature - see `docs/adr/0007-synthetic-truth-isolation.md`.
- No real customer, personal, or bank-account data will ever be placed in this repository. See `docs/assumptions_and_limitations.md`. (The two individual-level datasets acquired in Phase 2 are decades-old, anonymized public research datasets from Taiwan and Germany - not real customers of any kind, let alone of the fictional CredLens scenario; the Phase 4A generator produces exclusively synthetic customers, with no CPF-shaped or otherwise document-like identifiers, mechanically checked on every run.)
