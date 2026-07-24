# CC BY 4.0 — applies to: uci-default-credit, south-german-credit

Both UCI-hosted sources in this registry are licensed under the
**Creative Commons Attribution 4.0 International (CC BY 4.0)** license.

Full legal text: <https://creativecommons.org/licenses/by/4.0/legalcode>
Human-readable summary: <https://creativecommons.org/licenses/by/4.0/>

Confirmed directly against `archive.ics.uci.edu/api/dataset?id=350` and
`?id=522` on 2026-07-23 (see `data/metadata/source_registry.yaml`).

## What CC BY 4.0 permits

- Share — copy and redistribute the material in any medium or format.
- Adapt — remix, transform, and build upon the material for any purpose,
  even commercially.

## What it requires

- **Attribution** — credit must be given, a link to the license provided,
  and any changes indicated. This must be done "in any reasonable manner,
  but not in any way that suggests the licensor endorses you or your use."

CredLens satisfies this by citing each dataset with its DOI wherever the
data is referenced in documentation (see the `citation` field in
`data/metadata/source_registry.yaml`), and by never presenting either
dataset as CredLens-original data.

## Required citations

**uci-default-credit**:
> Yeh, I-Cheng. (2009). Default of Credit Card Clients [Dataset]. UCI
> Machine Learning Repository. https://doi.org/10.24432/C55S3H

**south-german-credit**:
> Groemping, U. (2019). South German Credit [Dataset]. UCI Machine
> Learning Repository. https://doi.org/10.24432/C5X89F

## Redistribution note

CC BY 4.0 permits redistributing the data itself (with attribution), so
the raw files acquired under this license are not blocked from being
re-shared by CredLens's own MIT code license — but the two licenses are
independent: MIT covers CredLens's code, CC BY 4.0 covers these two
datasets specifically. See `docs/data_licensing.md`.
