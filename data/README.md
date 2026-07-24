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
└── metadata/                   # Provenance records - versioned, contains NO data content
    ├── source_registry.yaml    # What each source is, its license, its lifecycle status
    ├── dataset_roles.yaml      # Why each source has its role (short version of docs/dataset_selection.md)
    ├── file_manifest.csv       # Every acquired file: path, size, SHA-256, retrieval time, row/col counts
    ├── schemas/                 # Documented column lists per source (used to detect drift)
    └── licenses/                 # License text and verification evidence per source
```

`interim/` and `processed/` remain genuinely empty in this phase - no transformation has happened yet (see `docs/roadmap.md`, phases 3-6). `external/` remains empty - no additional reference data was needed beyond the five registered sources.

## What's versioned vs. git-ignored

- **Versioned**: this file, and everything under `data/metadata/` (YAML/CSV/Markdown provenance records - never the data itself).
- **Git-ignored**: everything under `data/raw/`, `data/external/`, `data/interim/`, `data/processed/`. Verified with `git check-ignore -v` in this session - see the Phase 2 final report.

This means a fresh clone of this repository has `data/metadata/` populated but `data/raw/` empty. That's intentional and reproducible: run `uv run credlens data fetch --source <id>` for each source listed in `data/metadata/source_registry.yaml` to repopulate it (see `docs/data_sources.md` for exact commands), then `uv run credlens data verify` and `uv run credlens data audit` to reproduce this session's checksums and audit findings.

## Rules that apply here

- Nothing under `data/raw/`, `data/external/`, `data/interim/`, or `data/processed/` is ever committed to git.
- Every acquired file's license is recorded in `data/metadata/source_registry.yaml` and `docs/data_licensing.md` before acquisition, not after.
- Synthetic data (not yet built - see `docs/data_strategy.md`) will be clearly and mechanically distinguishable from public data once it exists; the two are never blended silently.
- No real customer, personal, or bank-account data will ever be placed in this repository. See `docs/assumptions_and_limitations.md`. (The two individual-level datasets acquired this phase are decades-old, anonymized public research datasets from Taiwan and Germany - not real customers of any kind, let alone of the fictional CredLens scenario.)
