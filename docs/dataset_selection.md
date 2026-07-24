# Dataset Selection (Phase 2)

This document formally decides the role of every data source evaluated in Phase 2, using a weighted scoring matrix for the three candidates that genuinely compete for the same job — being the individual-level credit-risk benchmark this project builds and tests analytics/audit code against. It also documents why the other two source types (BCB SGS, future synthetic data) are **not** scored in that same matrix: they play structurally different roles, so scoring them against "does this look like a good individual-level credit dataset" would be comparing apples to oranges.

All facts used below (row/column counts, license, DOI) were independently verified against each source's official metadata on 2026-07-23 — see `data/metadata/source_registry.yaml` for the full record and `docs/data_licensing.md` for the license-specific evidence.

## Scope of this matrix

**Scored here** (competing for the same role — individual-level benchmark):

- `uci-default-credit` — Default of Credit Card Clients (UCI)
- `south-german-credit` — South German Credit (UCI)
- `home-credit` — Home Credit Default Risk (Kaggle, blocked)

**Not scored here** (different role, decided directly — see `data/metadata/dataset_roles.yaml`):

- `bcb-sgs-20570` / `bcb-sgs-21112` — aggregate macroeconomic context, not individual-level data. Their fitness is about being official, correctly attributed, and genuinely relevant to a Brazilian lending scenario, not about competing with an individual-level credit dataset.
- Future synthetic operational layer — doesn't exist yet; it's a build decision (documented in `docs/data_strategy.md`), not an acquisition decision.

## Criteria and weights

Weights are a project decision, not a scientific fact, and are stated here so the reasoning is inspectable and challengeable. They sum to exactly 100. Heavier weight went to criteria that are **gating** for a reproducible public portfolio project (license clarity, reproducibility, absence of required credentials) and to core content fit (relevance, target, longitudinal/portfolio structure) — lighter weight went to criteria that matter but are secondary at this phase (recency, Brazil-specific compatibility, since none of these datasets is expected to be geographically representative of the fictional scenario anyway; see `docs/assumptions_and_limitations.md`).

| # | Criterion | Weight | Why this weight |
|---|---|---:|---|
| 1 | Relevance to credit risk | 10 | Core domain fit - must be a real credit/default problem. |
| 2 | Variable richness | 6 | More features support richer future analysis, but is not gating. |
| 3 | Presence of a clear target variable | 6 | Required for any future classification-style benchmark use. |
| 4 | Longitudinal structure / fit for portfolio-style analysis | 10 | Directly serves CredLens's vintage/roll-rate ambitions (docs/kpi_dictionary.md) - a single snapshot is a real structural limitation. |
| 5 | Relational / multi-table structure | 4 | Nice-to-have realism; not required for the benchmark role. |
| 6 | Documentation quality | 8 | A dataset this project can't fully explain shouldn't be used. |
| 7 | License clarity | 12 | Gating: an unclear license blocks any legitimate use at all. |
| 8 | Redistribution permission | 6 | Affects whether derived artifacts (e.g. audit reports quoting values) are safe to publish. |
| 9 | Reproducibility of acquisition (scriptable, no manual steps) | 10 | Gating for a portfolio project whose entire premise is reproducibility. |
| 10 | Source stability (won't disappear/change silently) | 4 | Affects long-term reproducibility of this repository. |
| 11 | Absence of required credentials | 6 | Gating per this project's explicit rule against embedding/requesting credentials. |
| 12 | Fit for CredLens's specific scope (docs/kpi_dictionary.md) | 6 | Distinct from #1: not just "is it credit risk," but "does it serve *this* project's planned KPIs." |
| 13 | Ethical limitations (known sensitive/ambiguous fields) | 3 | Relevant now for documentation; more relevant once modeling starts. |
| 14 | Leakage risk (documented or plausible) | 4 | Relevant now for documentation; critical once modeling starts. |
| 15 | Recency | 2 | Nice-to-have; none of the three candidates is recent, so this barely differentiates them. |
| 16 | Compatibility with a Brazilian scenario | 3 | None of the three is Brazilian; this mostly differentiates "generic consumer lending" from "very different market/era." |

## Scores (0-5 per criterion, verified facts only)

| Criterion (weight) | uci-default-credit | south-german-credit | home-credit |
|---|---:|---:|---:|
| Relevance (10) | 5 | 4 | 5 |
| Variable richness (6) | 4 | 3 | 5 |
| Target variable (6) | 5 | 5 | 5 |
| Longitudinal/portfolio fit (10) | 2 | 1 | 4 |
| Relational structure (4) | 1 | 1 | 5 |
| Documentation (8) | 5 | 5 | 3 |
| License clarity (12) | 5 | 5 | 0 |
| Redistribution (6) | 5 | 5 | 0 |
| Reproducibility (10) | 5 | 5 | 0 |
| Source stability (4) | 5 | 5 | 3 |
| No credentials required (6) | 5 | 5 | 0 |
| CredLens scope fit (6) | 4 | 2 | 4 |
| Ethical limitations (3) | 3 | 2 | 2 |
| Leakage risk (4) | 4 | 4 | 2 |
| Recency (2) | 3 | 1 | 4 |
| Brazil compatibility (3) | 2 | 1 | 2 |

**Score rationale, briefly:**

- **uci-default-credit** loses points only on longitudinal structure (a single 6-month snapshot embedded as columns, not a true evolving panel), relational structure (one flat table), and recency (2005 data) - everything about *accessing and trusting* it scores maximally.
- **south-german-credit** scores similarly to uci-default-credit on access/trust criteria (both UCI, both CC BY 4.0, both fully scripted this session), but scores lower on richness, portfolio fit, recency (1973-1975), and ethical clarity (UCI's own documentation flags that its `personal_status_sex` column cannot reliably recover sex for all categories - see `docs/sensitive_attributes.md`).
- **home-credit** scores highest or tied-highest on every *content* criterion (richness, relational structure, longitudinal depth, recency) - it is genuinely the richest dataset evaluated. It scores **zero** on license clarity, redistribution, reproducibility, and credential-freedom, because none of these could be confirmed or satisfied in this phase: see `docs/data_licensing.md` for the specific evidence that its rules/data pages could not be read without an authenticated Kaggle session.

## Weighted results

Weighted score = Σ(weight × score) ÷ 5 (normalizes the 0-500 raw range to a 0-100 scale, since max score per row is 5).

| Candidate | Weighted score | Decision |
|---|---:|---|
| uci-default-credit | **83.8** | `primary_benchmark` |
| south-german-credit | **74.2** | `secondary_benchmark` |
| home-credit | **51.6** | `optional_restricted` (blocked this phase) |

This matches the roles already recorded in `data/metadata/dataset_roles.yaml`, which were reasoned qualitatively before this matrix was built - the matrix was used to check that reasoning, not to launder a predetermined answer. No weight was tuned after seeing this result.

## Sensitivity analysis

Per this phase's brief, this is a simple check, not a formal MCDM robustness analysis: **does the decision survive a large, deliberately biased reweighting in home-credit's favor?**

Scenario: halve the three criteria that most penalize home-credit's inaccessibility (license clarity 12→6, reproducibility 10→5, no-credentials 6→3, freeing 14 points), and give all 14 points to the three criteria where home-credit scores highest relative to the others (relevance 10→15, variable richness 6→11, relational structure 4→8).

| Candidate | Original | Under biased reweighting | Change |
|---|---:|---:|---:|
| uci-default-credit | 83.8 | 79.6 | −4.2 |
| south-german-credit | 74.2 | 68.0 | −6.2 |
| home-credit | 51.6 | 65.6 | +14.0 |

**Result: the ranking does not flip.** Even under a reweighting explicitly constructed to favor it as much as plausibly defensible, home-credit (65.6) still does not overtake south-german-credit (68.0), let alone uci-default-credit (79.6). The `primary_benchmark` decision is robust; the `secondary_benchmark` vs. `optional_restricted` gap narrows substantially but does not invert. This is a reasonable result: no amount of content richness compensates for a source that could not be verified as legally and mechanically reproducible in this phase, which is exactly the gating property those three halved criteria were weighted to protect.

## Decision

| Source | Final role | Status |
|---|---|---|
| uci-default-credit | `primary_benchmark` | `verified` (acquired and audited - see `docs/data_quality_audit.md`) |
| south-german-credit | `secondary_benchmark` | `verified` (acquired and audited) |
| home-credit | `optional_restricted` | `blocked` (`BLOCKED_REQUIRES_USER_ACCESS`) |
| bcb-sgs-20570 | `market_context` | `verified` (acquired and audited) |
| bcb-sgs-21112 | `market_context` | `verified` (acquired and audited) |
| future synthetic operational layer | `future_synthetic` | not built (design-only, per `docs/data_strategy.md`) |

No candidate evaluated this phase was scored and then outright `rejected`. Other candidates named in Phase 1's `docs/data_strategy.md` (e.g., other Kaggle credit datasets, Lending Club historical data) were not individually re-evaluated in Phase 2 - the two UCI datasets already satisfied the primary/secondary benchmark roles well enough, under the criteria above, that expanding the candidate pool further was not necessary to reach a defensible decision this phase.
