# Data Sources (Operational Reference)

This document describes, per source, what it actually is and how CredLens acquires it. For *why* each source has its role, see `docs/dataset_selection.md`. For license text and verification evidence, see `docs/data_licensing.md`. For column-level detail, see `docs/data_dictionary.md`.

All five registered sources are acquired the same way: `uv run credlens data fetch --source <id>`. Nothing is downloaded automatically by any other command - `credlens data audit` and `credlens data sources` never touch the network (see `docs/architecture.md`).

## uci-default-credit — Default of Credit Card Clients

- **What it is**: 30,000 individual credit card clients in Taiwan, with 6 months of repayment/billing history (April-September 2005) and a binary "default next month" target.
- **Acquisition**: a single HTTPS GET to `https://archive.ics.uci.edu/static/public/350/data.csv` - UCI's own documented data API endpoint (`archive.ics.uci.edu/api/dataset?id=350`), not a scraped page. No authentication.
- **File**: `data/raw/uci_default_credit/default_of_credit_card_clients.csv` - a plain CSV, one header row (`ID,X1,...,X23,Y`), 30,000 data rows. Verified byte-for-byte against a fresh inspection before finalizing the acquisition code (see the CLI's actual run in this session's validation log).
- **Command**: `uv run credlens data fetch --source uci-default-credit`

## south-german-credit — South German Credit

- **What it is**: 1,000 German credit applicants (1973-1975), 21 features, a binary good/bad credit-compliance target. Explicitly published by UCI to **correct** known coding errors in the older, widely-used Statlog German Credit dataset - see `docs/dataset_selection.md` for why this version was used instead of Statlog, per this phase's brief.
- **Acquisition**: a single HTTPS GET to `https://archive.ics.uci.edu/static/public/522/south+german+credit.zip` (UCI's documented static-files bundle for this dataset - its data API's `data_url` field is `null` for this dataset, so the zip bundle is the correct official artifact, not a fallback). No authentication.
- **File**: `data/raw/south_german_credit/south_german_credit.zip`, plus its three extracted members (see "Archive extraction" below):
  - `SouthGermanCredit.asc` - whitespace-delimited, **header row present** (original German short column codes: `laufkont laufzeit moral ...`), 1000 data rows.
  - `codetable.txt` - human-readable category code definitions for every categorical column (used to write `docs/data_dictionary.md`).
  - `read_SouthGermanCredit.R` - the dataset authors' own R loading script (kept for reference; not executed by CredLens).
- **Command**: `uv run credlens data fetch --source south-german-credit`

### Archive extraction

`south-german-credit` is the only registered source distributed as an archive. `credlens data fetch` downloads the `.zip` (which remains on disk as the authoritative original artifact, checksummed and manifested like any other file) and then extracts its members into the same raw directory via `credlens.data.downloader.extract_zip_safely`, which validates every member's resolved path stays inside the destination directory before writing (defense against a "zip slip" path-traversal archive) and refuses to overwrite an existing extracted file without `--force`. Extraction decompresses already-downloaded bytes; it does not alter their content - the `.asc` file is audited exactly as UCI packaged it.

## home-credit — Home Credit Default Risk

- **What it is**: a richer, multi-table Kaggle competition dataset (application-level plus bureau/previous-application/installment history). See `docs/dataset_selection.md` for why it scores well on content but is not usable this phase.
- **Acquisition**: **blocked**. `uv run credlens data fetch --source home-credit` returns a clean, non-crashing `BLOCKED_REQUIRES_USER_ACCESS` message and a non-zero exit code - it never attempts a network call. See `docs/data_licensing.md` for the specific evidence gathered before making this call, and `data/metadata/licenses/kaggle-home-credit-notes.md` for what a human would need to do to unblock it in a future session.

## bcb-sgs-20570 / bcb-sgs-21112 — Banco Central do Brasil SGS series

- **What they are**: two official, aggregate, monthly Brazilian indicators - free-rate credit portfolio balance for individuals (20570) and its 90+ days-overdue delinquency rate (21112). Macro context for the fictional CredLens scenario, never individual-level data (see `docs/sensitive_attributes.md`).
- **Acquisition**: `credlens.data.bcb_client.fetch_series` queries `https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados` with an **explicit, required** `dataInicial`/`dataFinal` range (DD/MM/AAAA) - this client never queries an open-ended range. No authentication.
- **Command**: `uv run credlens data fetch --source bcb-sgs --start 01/01/2015 --end 23/07/2026` (or `--source bcb-sgs` alone to use `config/base.yaml`'s `data.bcb_default_start_date` and today's date). `bcb-sgs` is a group alias that fetches every registered series whose `acquisition_method` is `bcb_sgs` - both 20570 and 21112 - in one command.
- **Files**: `data/raw/bcb_sgs/bcb_sgs_20570.json`, `data/raw/bcb_sgs/bcb_sgs_21112.json` - each the verbatim BCB response (a JSON array of `{"data": "DD/MM/AAAA", "valor": "<string>"}` objects), with `valor` preserved as the string BCB returns - no decimal-separator assumption or numeric coercion is applied at acquisition time (that belongs to a later analytical phase, and would need to account for Brazilian `,` decimal separators explicitly when it happens).

### Date-window chunking, and a real bug this caught

Per this phase's brief, long queries are partitioned into sequential date windows (`config/base.yaml`'s `data.bcb_max_days_per_request`, default 3650 days / ~10 years, matching BCB's documented constraint on certain daily series) rather than issued as one unbounded request. Partitioning was exercised for real in this session (an 11.5-year query for these monthly series, split into 2 windows), and it **surfaced a genuine bug**: BCB's SGS API applies *month-inclusive* date semantics, so a window ending mid-month and the next window starting the following day both legitimately returned that same month's single observation - an exact duplicate row (same date, same value) at the chunk boundary, correctly flagged by `credlens data audit` as a `candidate_anomaly` the first time this was run for real.

This was fixed in `credlens.data.bcb_client._deduplicate_boundary_observations`, which removes only byte-for-byte identical repeats across windows (logging a warning when it does) - it does not touch a case where the same date appeared with two *different* values, which would instead surface as a data-quality finding for a human to look at, not be silently resolved. Re-running the fetch and audit after the fix confirmed the duplicate finding disappeared and checksums/row counts updated accordingly. This is left in this document deliberately, as a real example of the audit tooling doing its job.

## What is explicitly not done at acquisition time

- No missing-date filling (a documented rule for this phase - see the Phase 2 brief).
- No numeric parsing of BCB's `valor` field (kept as the original string).
- No column renaming, recoding, or type coercion of any raw file's actual content.
- No merging of any of these five sources with each other, or with anything else, at this phase (see `docs/assumptions_and_limitations.md` for why mixing Taiwan/Germany/Brazil data would be treated as though it were one coherent population would be a real error).
