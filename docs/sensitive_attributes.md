# Sensitive Attributes and Fairness Limitations

This document records what is known about sensitive and potentially-proxy attributes in the two individual-level datasets acquired this phase. It is an audit, not a fairness certification, and not a decision about whether or how these datasets may ever be used for modeling - see `docs/assumptions_and_limitations.md` for why this project cannot authorize real-world credit use of anything it produces.

**No group-level credit decision is proposed anywhere in this document.** No dataset or model is described as "fair" or "safe to use" merely because it excludes a sensitive attribute directly - that framing is explicitly rejected below (see "Why exclusion alone proves nothing").

## uci-default-credit (Taiwan, 2005)

| Column | Attribute type | Notes |
|---|---|---|
| `X2` (SEX) | Explicit demographic | 1 = male, 2 = female (per UCI documentation). |
| `X3` (EDUCATION) | Explicit demographic / socioeconomic proxy | 1 = graduate school, 2 = university, 3 = high school, 4 = others. Education level is a well-known proxy for socioeconomic status and, in some contexts, for other protected characteristics. |
| `X4` (MARRIAGE) | Explicit demographic | 1 = married, 2 = single, 3 = others. |
| `X5` (AGE) | Explicit demographic | Age is a protected characteristic under fair-lending frameworks in most jurisdictions that have them. |
| `X1` (LIMIT_BAL) | Possible proxy | Credit limit can correlate with income/wealth, which itself correlates with protected characteristics; not proven here, only flagged. |

No combined/derived demographic column exists in this dataset (unlike south-german-credit's `famges` below) - each attribute is separately coded.

## south-german-credit (Germany, 1973-1975)

| Column | Attribute type | Notes |
|---|---|---|
| `famges` (personal_status_sex) | **Combined, ambiguously coded** demographic | UCI's own documentation states this explicitly: *"sex cannot be recovered from the variable, because male singles and female non-singles are coded with the same code (2); female widows cannot be easily classified, because the code table does not list them in any of the female categories."* This is a source-acknowledged limitation, not something this audit discovered independently - and it means any attempt to "just extract sex" from this column would silently produce wrong values for an unknown share of rows. |
| `gastarb` (foreign_worker) | Explicit, nationality-adjacent | Binary; foreign national origin is a protected characteristic in most fair-lending frameworks. |
| `alter` (age) | Explicit demographic | Same caution as uci-default-credit's `X5`. |
| `beruf` (job quality, ordinal) | Possible proxy | Occupation-quality gradings can correlate with protected characteristics. |
| `wohn` (housing type) | Possible proxy | Housing status can correlate with socioeconomic and, indirectly, demographic factors. |

## Small-group and coding-quality risk

- `south-german-credit` is only 1,000 rows with a *deliberately* oversampled bad-credit class (700 good / 300 bad, per UCI's own documentation) - any attribute cross-tabulation (e.g., `famges` × `kredit`) will have very small cell counts for some categories, which is a real statistical-reliability limitation independent of the coding-ambiguity issue above. Small-group statistics are easy to over-interpret; a future phase must report cell sizes alongside any such cross-tabulation, not just a rate.
- `uci-default-credit`'s `EDUCATION` and `MARRIAGE` columns each have an "others" catch-all category (per UCI's own coding) whose composition is undocumented - a future phase should treat that category's statistics cautiously rather than assuming it's a coherent group.

## Country, period, and the risk of transporting conclusions to Brazil

Both datasets predate the fictional CredLens scenario by decades and describe different legal/regulatory/social contexts (Taiwan, 2005; Germany, 1973-1975) than a present-day Brazilian digital lender. **Any demographic pattern observed in either dataset is a fact about that dataset's population in that country and era - it is not evidence about Brazilian applicants, and must never be presented as such.** This is the same rule already stated for the datasets generally in `docs/assumptions_and_limitations.md`, restated here specifically for demographic/fairness findings because this is exactly the kind of claim most likely to be mistakenly generalized.

## Why exclusion alone proves nothing

A model that never sees `X2`/`SEX` or `famges`/`gastarb` directly can still reproduce their effect through correlated variables (the "proxy" risk flagged above - e.g., `EDUCATION`, `beruf`, `wohn`). **Removing a sensitive column is not evidence of fairness by itself**, and this audit does not treat it that way anywhere in this project's documentation. Demonstrating the *absence* of proxy discrimination requires a dedicated fairness evaluation (e.g., outcome-rate comparisons across groups, holding other factors constant) that has not been performed in this phase and is out of scope for it - see `docs/roadmap.md`.

## Auditing a dataset is not authorizing its use

This document, and the target/leakage audit it complements (`docs/target_and_leakage_audit.md`), describe what these datasets *contain*. Neither document, individually or together, constitutes:

- A determination that either dataset is safe to model on for any real decision.
- A fairness certification of any kind.
- Legal or regulatory advice about fair-lending compliance in any jurisdiction.

Per `docs/assumptions_and_limitations.md`, any real-world use of anything built from these datasets would require independent legal, statistical, and regulatory review that this project does not perform and does not claim to perform.

## What a future phase must do before modeling with either dataset

1. Read this document and `docs/target_and_leakage_audit.md` first.
2. Decide explicitly whether sensitive/proxy columns are included, and document that decision and its justification (not just make the choice implicitly).
3. If a model is built, run an outcome-rate/proxy check across the demographic groups identified above before reporting any result, and report cell sizes alongside any rate for small groups.
4. Never describe a finding from either dataset as representative of Brazil, of any real institution, or of any population beyond the dataset's own documented country/period.
