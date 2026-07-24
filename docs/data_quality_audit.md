# Data Quality Audit

This is the narrative summary of the reproducible, code-generated audit in `reports/data_audit/quality_metrics.json` (produced by `uv run credlens data audit`), plus a small number of manual spot-checks noted explicitly as manual below. **Nothing in this document was used to modify any raw file** - `data/raw/` is exactly what was downloaded, byte for byte (see `docs/data_sources.md` for checksums and `uv run credlens data verify`'s output in this session's validation log).

## What the automated audit checks

Per source, `credlens.data.audit.audit_dataframe` (via `credlens.data.profiler`) computes: row/column counts, per-column dtype, missing count/percentage, exact cardinality, constant-column detection, possible-identifier detection (unique value per row), min/max for numeric columns, top-10 category frequencies for columns with ≤30 distinct values, infinite-value detection, exact full-row duplicate detection, and a comparison against each source's documented column list (`data/metadata/schemas/*.yaml`).

**What it does not check**: value-*domain* conformance within a column - e.g., "does this categorical column only contain the codes the source documents?" - is out of scope for `credlens data audit` (Phase 2) itself and remains so; that command's job stays structural profiling, not domain validation. **As of Phase 3**, domain conformance is checked by a separate, purpose-built command: `credlens contracts validate --mode audit`, driven by the declared `domain:` field in `contracts/raw/*.yaml`. The EDUCATION/MARRIAGE finding below - originally found by a one-off manual pandas check in Phase 2 - is reproduced automatically by that command today; see "Manual finding" below and `docs/data_contracts.md`'s "Real bugs this system caught" section for how the automation was verified against this exact finding.

## Results by source

### uci-default-credit (30,000 rows × 25 columns)

- **Schema match**: exact - no unexpected or missing columns versus `data/metadata/schemas/uci-default-credit.yaml`.
- **Missing values**: 0 across all columns - **confirms** UCI's own "no missing values" claim (this is a confirmation, not an assumption - the check ran against the actual acquired file).
- **Exact duplicate rows**: 0.
- **Constant columns**: none.
- **Infinite values**: none.
- **Automated finding**: `ID` is a `documented_characteristic` (unique per row, matches UCI's documented index column - not flagged as a surprise).
- **Class balance** (technical diagnostic only, not a business finding - see the note below): `Y` = 0 (no default) for 23,364 rows (77.9%), `Y` = 1 (default) for 6,636 rows (22.1%).

#### Finding: undocumented category codes in `EDUCATION` and `MARRIAGE` (manually found in Phase 2, now automated in Phase 3)

UCI documents `X3` (EDUCATION) as taking values 1-4 (graduate school / university / high school / others) and `X4` (MARRIAGE) as taking values 1-3 (married / single / others). The acquired file's actual category frequencies are:

- `X3` (EDUCATION): `{1: 10585, 2: 14030, 3: 4917, 4: 123, 5: 280, 6: 51, 0: 14}` - codes `0`, `5`, and `6` are **not** in UCI's documented 1-4 range (345 rows total).
- `X4` (MARRIAGE): `{0: 54, 1: 13659, 2: 15964, 3: 323}` - code `0` is **not** in UCI's documented 1-3 range (54 rows).

**Category: `confirmed_problem`** (a real, checkable mismatch between the source's own documentation and the acquired file - not a guess). This is also a widely-recognized characteristic of this specific, heavily-used benchmark dataset in the broader data science community - it is being reported here as a confirmed, independently-verified fact about the acquired file, not presented as a novel discovery. It matters for any future modeling phase: `0`/`5`/`6` in EDUCATION and `0` in MARRIAGE need an explicit handling decision (e.g., treat as "unknown/other") rather than being silently assumed to fit the documented four/three categories.

Originally found by a one-off manual pandas check in Phase 2. As of Phase 3, `contracts/raw/uci_default_credit.yaml` declares `X3: {in_set: [1,2,3,4]}` and `X4: {in_set: [1,2,3]}`, and `credlens contracts validate --contract uci_default_credit --path data/raw/uci_default_credit/default_of_credit_card_clients.csv --mode audit` reproduces the same 345/54 counts automatically, with a pinned regression test (`tests/test_contracts_regression.py`) guarding against this detection silently breaking in the future.

### south-german-credit (1,000 rows × 21 columns)

- **Schema match**: exact - no unexpected or missing columns versus `data/metadata/schemas/south-german-credit.yaml`.
- **Missing values**: 0 across all columns - **confirms** UCI's "no missing values" claim.
- **Exact duplicate rows**: 0.
- **Constant columns**: none.
- **Infinite values**: none.
- **Automated finding**: none - this source produced zero findings, meaning nothing structurally unusual was detected against its schema or general data-quality checks.
- **Domain check** (manual in Phase 2, now also covered by `contracts/raw/south_german_credit.yaml` in Phase 3): `famges` (`{1: 50, 2: 310, 3: 548, 4: 92}`) and `kredit` (`{0: 300, 1: 700}`) both fall entirely within their documented code ranges (1-4 and 0-1 respectively) - no equivalent of the uci-default-credit finding above.
- **Class balance** (technical diagnostic only): `kredit` = good for 700 rows (70%), bad for 300 rows (30%) - **this matches UCI's own documentation exactly**, which states the sample is deliberately stratified with bad credits oversampled. This is a `documented_characteristic`, not a finding about real-world default rates of any kind.

### bcb-sgs-20570 (137 rows × 2 columns)

- **Missing values**: 0.
- **Exact duplicate rows**: 0 (after the chunking-boundary fix - see `docs/data_sources.md` for the bug this audit tool caught and how it was fixed, re-verified in this session).
- **Automated findings**: `data` is a `documented_characteristic` (the series' own date/time index, unique per row by definition); `valor` is a `hypothesis_requiring_investigation` (unique per row - plausible for a continuously moving portfolio-balance aggregate, but not asserted as expected here, since nothing in BCB's documentation guarantees it).
- **Phase 3**: `contracts/raw/bcb_sgs_20570.yaml` declares `data` as the primary key (catches any reintroduced duplicate date) plus the `bcb_dates_strictly_increasing` business rule (catches any reintroduced out-of-order/overlapping chunk merge) - both are regression-tested in `tests/test_contracts_regression.py` against a synthetic reproduction of the original chunking bug, and both currently pass cleanly against the real acquired file.

### bcb-sgs-21112 (137 rows × 2 columns)

- **Missing values**: 0.
- **Exact duplicate rows**: 0 (same fix as above).
- **Automated findings**: `data` is a `documented_characteristic`. `valor` has 109 distinct values across 137 rows (28 repeats) - below the identifier threshold, so no finding was raised; a repeated percentage value across different months is unsurprising for a rate reported to limited decimal precision, and is not flagged as anomalous.
- **Phase 3**: same PK + `bcb_dates_strictly_increasing` protection as bcb-sgs-20570 above, via `contracts/raw/bcb_sgs_21112.yaml`.

## Note on class-balance figures above

The `Y` and `kredit` percentages above are **technical diagnostics about these specific benchmark datasets** - they describe UCI's sampling of Taiwan (2005) and Germany (1970s) data, respectively. They are not a finding about credit risk in general, not a finding about any real institution, and specifically not a finding about Brazil or about the fictional CredLens scenario. See `docs/assumptions_and_limitations.md`.

## Category summary (per finding, across all four audited sources)

| Category | Count | Examples |
|---|---:|---|
| `confirmed_problem` | 1 | Undocumented EDUCATION/MARRIAGE codes (uci-default-credit; manual finding) |
| `candidate_anomaly` | 0 | (the one true anomaly found this session - the BCB chunking duplicate - was fixed and re-verified before this report was finalized; see `docs/data_sources.md`) |
| `documented_characteristic` | 4 | `ID` (uci-default-credit), `data` (both BCB series), and the confirmed class-balance/stratification facts above |
| `hypothesis_requiring_investigation` | 1 | `valor` uniqueness in bcb-sgs-20570 |
| `structural_limitation` | 2 (qualitative, not from the automated tool) | uci-default-credit is a single snapshot, not a longitudinal panel (see `docs/dataset_selection.md`); south-german-credit is 50 years old and too small to anchor portfolio-level analysis alone |

## Rules this audit followed

No raw file was modified to produce this report. No duplicates were removed, no missing values were imputed, no column was renamed or recoded, and no train/test split or model was created - all explicitly out of scope for this phase.

## Phase 3 addendum: from manual findings to automated, tested checks

Every "manual finding" recorded above (EDUCATION/MARRIAGE domain codes, the BCB chunking-boundary duplicate/ordering) is, as of Phase 3, reproduced by an automated command (`credlens contracts validate --mode audit`) backed by a permanent pytest regression test, not a one-off script run during this session and then discarded. This document's original manual findings are left in place unedited (history should stay visible) with notes added pointing to their automated equivalents - see `docs/data_contracts.md` for the full contracts system and `tests/test_contracts_regression.py` for the pinned regression tests.
