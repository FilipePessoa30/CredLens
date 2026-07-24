# Target and Leakage Audit

This is a structural audit, not a modeling exercise. **No variable is removed from any raw file.** This document classifies each dataset's columns relative to a specific "decision instant" and proposes a future policy for what a later modeling phase should and shouldn't use - it does not build, train, or evaluate anything.

## Method

For each individual-level dataset, this audit:

1. Identifies the target variable.
2. Defines the conceptual instant a real decision would be made (this is the single most important step - a variable is only "leakage" *relative to* a specific decision instant, never in the abstract).
3. Classifies every column as: available at the decision instant, known only after it, ambiguous, an identifier, sensitive, or a leakage candidate.
4. States plainly which columns could not enter a credit-**granting** (origination) model, and why.
5. Distinguishes which of four model types (origination / behavioral / collections / portfolio monitoring) the dataset's own structure actually supports.

`bcb-sgs-20570` and `bcb-sgs-21112` are aggregate, national-level time series with no loan-level target and no applicant-level decision instant - this entire framework does not apply to them, and they are excluded below for that reason, not because they were skipped.

`home-credit` was not acquired (see `docs/data_licensing.md`) - it cannot be audited against data this project doesn't have, so it is also excluded, and any future phase that unblocks it must run this same audit before using it.

---

## uci-default-credit

- **Target**: `Y` - default payment next month (1 = default, 0 = no default).
- **Decision instant**: this dataset's own design fixes the instant implicitly - it observes 6 months of an *existing* account's repayment/billing behavior (September 2005 back to April 2005) and predicts default in the month immediately after the observation window. That is a **behavioral / early-warning decision instant on an existing account**, not an origination decision on a new applicant - there is no point in this dataset where an applicant has no history yet.

| Column(s) | Classification | Notes |
|---|---|---|
| `ID` | Identifier | Not a feature; row identifier only. |
| `X1` (LIMIT_BAL) | Ambiguous | Available at the behavioral decision instant, but its own value was itself set by a prior, unobserved credit decision - using it in a *new-applicant* origination model would be circular. |
| `X2` (SEX), `X3` (EDUCATION), `X4` (MARRIAGE), `X5` (AGE) | Available, but **sensitive** | Demographic; available at any decision instant, but require fair-lending review before any modeling use - see `docs/sensitive_attributes.md`. |
| `X6`-`X11` (PAY_0..PAY_6, repayment status) | **Known only after origination** | Describes repayment behavior in the 6 months *preceding* the target month, on an account that already exists. |
| `X12`-`X17` (BILL_AMT1-6) | **Known only after origination** | Same category as above - post-origination account behavior. |
| `X18`-`X23` (PAY_AMT1-6) | **Known only after origination** | Same category as above. |
| `Y` | Target | Defined for the month *after* the X6-X23 observation window - correctly sequenced relative to the predictors within this dataset's own intended use. |

### What could not enter a credit-granting (origination) model

**All of X6 through X23** (18 of the 23 explanatory variables). A first-time applicant has no repayment history, no bill statements, and no payment history with this lender yet - none of these columns could exist at the moment a brand-new application is being decided. Only `X2`-`X5` (demographics, subject to fair-lending review) and, ambiguously, `X1` would be available at a genuine origination instant. **This dataset is not fit for building or demonstrating a credit-granting model** - it is fit for a behavioral/monitoring model on accounts a lender already holds, which is a materially different decision (and a different stakeholder - Collections/Risk monitoring an existing book, not Credit approving new applications; see `docs/stakeholder_map.md`).

### Known "trivial predictor" caution (not leakage, but worth flagging)

`X6` (PAY_0, the most recent observed repayment status) is well documented in the broader literature on this dataset as the single strongest predictor of `Y`. This is not leakage - `X6` genuinely precedes `Y` in time - but a future model that leans almost entirely on "was this account already late last month" risks looking accurate while adding little real underwriting insight beyond what a simple rule would already capture. Worth stating explicitly before any future phase reports a model accuracy number on this dataset.

---

## south-german-credit

- **Target**: `kredit` (English: `credit_risk`) - good/bad credit compliance.
- **Decision instant**: unlike uci-default-credit, every one of this dataset's 20 predictor columns describes the applicant's situation **at the time of the credit application** - there is no post-origination behavioral data at all. This dataset's structure genuinely matches an **origination (credit-granting) decision instant**.

| Column | Classification | Notes |
|---|---|---|
| `laufkont` (status), `sparkont` (savings), `beszeit` (employment_duration) | Available at origination | Standard applicant-situation fields. |
| `moral` (credit_history) | Available at origination, with a caveat | Bureau-style prior-history summary; available like a credit bureau pull would be, but "concurrent credits" phrasing (per UCI's own variable description) means its exact cutoff relative to the application instant isn't fully pinned down by the documentation. |
| `verw` (purpose), `hoehe` (amount) | Available at origination | Requested loan characteristics. |
| `rate` (installment_rate) | **Ambiguous** | Defined as installment amount relative to income - if the installment amount is itself a product of the very decision being modeled (how much to lend, on what terms), this column is partly circular for a strict pre-decision origination model. Flagged for investigation before use, not excluded. |
| `famges` (personal_status_sex) | Available, but **sensitive and ambiguously coded** | UCI's own documentation states sex cannot be reliably recovered from this column for all categories - see `docs/sensitive_attributes.md`. |
| `buerge` (other_debtors), `wohnzeit` (present_residence), `verm` (property), `alter` (age), `weitkred` (other_installment_plans), `wohn` (housing), `bishkred` (number_credits), `beruf` (job), `pers` (people_liable), `telef` (telephone) | Available at origination | Standard applicant-situation fields. |
| `gastarb` (foreign_worker) | Available, but **sensitive** | Nationality-adjacent attribute; fair-lending review required before any modeling use. |
| `kredit` (credit_risk) | Target | — |

### What could not enter a credit-granting (origination) model

**None of the 20 predictors are structurally excluded** - this is the opposite finding from uci-default-credit, and the main reason `south-german-credit` is scored as more origination-shaped in `docs/dataset_selection.md` despite being far smaller and older. `rate` (installment_rate) is flagged as needing investigation for circularity before use, not excluded outright, since the dataset's own documentation doesn't fully resolve the question.

---

## Model-type differentiation (synthesis)

The Phase 2 brief requires distinguishing four model types. Based only on what these two datasets' own structures actually support:

| Model type | What it needs | Supported by |
|---|---|---|
| **Origination (concessão)** | Only pre-decision applicant information; no history with this specific credit relationship. | `south-german-credit` (structurally); **not** `uci-default-credit` (18/23 variables are post-origination). |
| **Behavioral (comportamental)** | Ongoing account history to predict near-future risk on an existing relationship. | `uci-default-credit` (structurally); **not** `south-german-credit` (no behavioral columns exist). |
| **Collections (cobrança)** | Delinquency-stage and collections-action/outcome data. | **Neither dataset.** As of Phase 3, this is designed (not yet populated) in the synthetic operational layer's `collection_events`, `write_off_events`, and `recovery_events` contracts - see `docs/conceptual_data_model.md` and `contracts/operational/collection_events.yaml`. |
| **Portfolio monitoring** | Aggregate, time-indexed views of the whole book. | Not directly - `bcb-sgs-20570`/`bcb-sgs-21112` provide market-level (not portfolio-level) monitoring *context* only; no portfolio-level monitoring dataset exists yet. Phase 3's `account_monthly_snapshots` contract designs the future portfolio-level monthly view - also not yet populated. |

## Future policy proposal (not implemented)

If a later phase builds a model on these datasets, this audit proposes (for that phase to formally adopt or revise, not something enacted here):

1. Never train a single model on `uci-default-credit` and `south-german-credit` combined, or claim one "credit risk model" spans both - they answer structurally different questions (behavioral vs. origination) on unrelated populations.
2. If `uci-default-credit` is used for an origination demo despite the mismatch above, `X6`-`X23` must be dropped and that limitation stated explicitly, not silently worked around.
3. Any use of `X2`-`X5` (uci-default-credit) or `famges`/`gastarb` (south-german-credit) requires the fair-lending review flagged in `docs/sensitive_attributes.md` before being treated as more than descriptive.
4. `rate` (south-german-credit) requires a documented decision on the circularity question above before being used as a model input.

No variable has been removed from any raw file to implement this policy - the raw files in `data/raw/` are untouched, exactly as acquired.

## Phase 3 note: this audit's core distinction is now enforced structurally, for the future synthetic layer

The origination-vs-behavioral leakage distinction this document draws by hand for `uci-default-credit`/`south-german-credit` is, as of Phase 3, also enforced by design in the synthetic operational layer's schema: `application_features` is a separate table populated only with values as they stood at `feature_snapshot_at = applications.submitted_at`, never updated afterward - see `docs/adr/0004-feature-freeze-at-proposal.md`. That ADR protects against the exact failure mode this document found in `uci-default-credit` (X6-X23 being unusable for origination because they only exist after the fact) from being reintroduced once a generator populates real rows. It does not retroactively fix anything about the two acquired public datasets, which remain as analyzed above.
