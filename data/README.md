# data/

This directory is a placeholder. It exists so the project's expected layout is
visible in version control, and it is preserved on purpose (`.gitignore`
excludes everything else under `data/` but explicitly keeps this file).

## Current status: empty by design

No dataset — public, synthetic, or otherwise — has been added to this
repository yet. This is the foundation phase of CredLens: business framing,
architecture, and project scaffolding only. Data acquisition is a later,
explicitly separate phase (see `docs/roadmap.md`, phase 2).

## What will live here in future phases

```text
data/
├── raw/         # Immutable, as-downloaded source files (git-ignored)
├── interim/     # Intermediate cleaning/staging outputs (git-ignored)
├── processed/   # Analysis-ready tables (git-ignored)
└── synthetic/   # Reproducibly generated synthetic operational data (git-ignored)
```

None of these subdirectories exist yet — they will be created, together with
the ingestion code that populates them, when the data acquisition phase
starts.

## Rules that will apply once data acquisition begins

- Nothing under `data/` (other than this file) is ever committed to git.
  Raw files, interim files, processed files, and synthetic files are all
  reproducible from documented code and a documented source, not from a
  copy sitting in the repository.
- Any public dataset used must have its license and terms of use recorded
  in `docs/data_strategy.md` before it is downloaded.
- Synthetic data must be clearly and mechanically distinguishable from
  public data (see `docs/data_strategy.md` for the labeling approach) —
  the two are never allowed to blend silently.
- No real customer, personal, or bank-account data will ever be placed in
  this repository. See `docs/assumptions_and_limitations.md`.
