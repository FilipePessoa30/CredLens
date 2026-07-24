# Data Dictionary

Column-level documentation for every acquired raw file, transcribed from each source's own official metadata - not inferred, not guessed. This is documentation of what the sources say their columns mean; it is not a data-quality assessment (see `docs/data_quality_audit.md` for that) and not a modeling recommendation (see `docs/target_and_leakage_audit.md` and `docs/sensitive_attributes.md`).

Machine-readable versions of the two UCI schemas live at `data/metadata/schemas/uci-default-credit.yaml` and `data/metadata/schemas/south-german-credit.yaml` (used by `credlens data audit` to detect divergence between documentation and the acquired file).

## uci-default-credit — Default of Credit Card Clients

Source: UCI API (`archive.ics.uci.edu/api/dataset?id=350`), verified 2026-07-23. 30,000 rows, 25 columns (23 explanatory variables + `ID` + `Y`).

| Column | Description | Type |
|---|---|---|
| `ID` | Row identifier assigned by UCI (not one of the original 23 explanatory variables). | Integer |
| `X1` (LIMIT_BAL) | Amount of the given credit (NT dollar) - includes individual and family (supplementary) credit. | Integer |
| `X2` (SEX) | 1 = male, 2 = female. | Categorical |
| `X3` (EDUCATION) | 1 = graduate school, 2 = university, 3 = high school, 4 = others. | Categorical |
| `X4` (MARRIAGE) | 1 = married, 2 = single, 3 = others. | Categorical |
| `X5` (AGE) | Age in years. | Integer |
| `X6` (PAY_0) | Repayment status, September 2005. -1 = pay duly; 1 = delay 1 month; 2 = delay 2 months; ... 9 = delay 9+ months. | Categorical |
| `X7`-`X11` (PAY_2..PAY_6) | Repayment status, August 2005 down to April 2005, respectively. Same coding as `X6`. | Categorical |
| `X12`-`X17` (BILL_AMT1-6) | Bill statement amount (NT dollar), September 2005 down to April 2005. | Integer |
| `X18`-`X23` (PAY_AMT1-6) | Amount previously paid (NT dollar), September 2005 down to April 2005. | Integer |
| `Y` | Default payment next month. 1 = default, 0 = no default. **Target variable.** | Binary |

No missing values are documented for this dataset (verified: `has_missing_values: no` in UCI's metadata, and confirmed empirically - see `docs/data_quality_audit.md`).

## south-german-credit — South German Credit

Source: UCI API (`archive.ics.uci.edu/api/dataset?id=522`), verified 2026-07-23, cross-checked against the dataset's own `codetable.txt` (downloaded alongside the data - see `docs/data_sources.md`). 1,000 rows, 21 columns. Column names below are the original German short codes used in the file's own header row; the English `variable_name` from UCI is given alongside each.

| Column (German / English) | Category codes (from `codetable.txt`) |
|---|---|
| `laufkont` / status | 1 = no checking account; 2 = ... < 0 DM; 3 = 0 <= ... < 200 DM; 4 = ... >= 200 DM / salary for ≥1 year |
| `laufzeit` / duration | Quantitative - credit duration in months. |
| `moral` / credit_history | 0 = delay in paying off in the past; 1 = critical account/other credits elsewhere; 2 = no credits taken/all credits paid back duly; 3 = existing credits paid back duly till now; 4 = all credits at this bank paid back duly |
| `verw` / purpose | 0 = others; 1 = car (new); 2 = car (used); 3 = furniture/equipment; 4 = radio/television; 5 = domestic appliances; 6 = repairs; 7 = education; 8 = vacation; 9 = retraining; 10 = business |
| `hoehe` / amount | Quantitative - credit amount in DM (per UCI: "result of a monotonic transformation; actual data and type of transformation unknown"). |
| `sparkont` / savings | 1 = unknown/no savings account; 2 = ... < 100 DM; 3 = 100 <= ... < 500 DM; 4 = 500 <= ... < 1000 DM; 5 = ... >= 1000 DM |
| `beszeit` / employment_duration | 1 = unemployed; 2 = < 1 yr; 3 = 1 <= ... < 4 yrs; 4 = 4 <= ... < 7 yrs; 5 = >= 7 yrs |
| `rate` / installment_rate | 1 = >= 35 (%); 2 = 25 <= ... < 35; 3 = 20 <= ... < 25; 4 = < 20 |
| `famges` / personal_status_sex | 1 = male: divorced/separated; 2 = female: non-single OR male: single; 3 = male: married/widowed; 4 = female: single. **See `docs/sensitive_attributes.md` - UCI itself documents that sex cannot be reliably recovered from this coding.** |
| `buerge` / other_debtors | 1 = none; 2 = co-applicant; 3 = guarantor |
| `wohnzeit` / present_residence | 1 = < 1 yr; 2 = 1 <= ... < 4 yrs; 3 = 4 <= ... < 7 yrs; 4 = >= 7 yrs |
| `verm` / property | 1 = unknown/no property; 2 = car or other; 3 = building society savings agreement/life insurance; 4 = real estate |
| `alter` / age | Quantitative - age in years. |
| `weitkred` / other_installment_plans | 1 = bank; 2 = stores; 3 = none |
| `wohn` / housing | 1 = for free; 2 = rent; 3 = own |
| `bishkred` / number_credits | 1 = 1; 2 = 2-3; 3 = 4-5; 4 = >= 6 |
| `beruf` / job | 1 = unemployed/unskilled - non-resident; 2 = unskilled - resident; 3 = skilled employee/official; 4 = manager/self-employed/highly qualified employee |
| `pers` / people_liable | 1 = 3 or more; 2 = 0 to 2 |
| `telef` / telephone | 1 = no; 2 = yes (registered under customer's name) |
| `gastarb` / foreign_worker | 1 = yes; 2 = no |
| `kredit` / credit_risk | 0 = bad; 1 = good. **Target variable.** |

No missing values are documented for this dataset (verified: `has_missing_values: no` in UCI's metadata, and confirmed empirically - see `docs/data_quality_audit.md`).

## bcb-sgs-20570 and bcb-sgs-21112 — BCB SGS series

Source: BCB SGS API response, structurally identical for both series (only the underlying values and their meaning differ - see `docs/data_sources.md` for what each series measures).

| Column | Description | Type |
|---|---|---|
| `data` | Reference date for the observation, `DD/MM/AAAA` string, as returned by BCB. One row per month. Acts as the series' natural key/index. | String (date) |
| `valor` | The indicator's value for that date, **as a string exactly as BCB returns it** - no numeric parsing or decimal-separator assumption is applied at acquisition time (see `docs/data_sources.md`). For `bcb-sgs-20570`: R$ millions. For `bcb-sgs-21112`: percentage. | String |

Neither series has a "missing values" claim to verify against, since BCB does not publish one - any gap would need to be checked against the series' own start date and expected monthly cadence, which is exactly what `docs/data_quality_audit.md` does for the acquired files.
