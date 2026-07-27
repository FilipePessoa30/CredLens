# Model Card - Behavioral Early-Warning Model (Phase 8)

**Status**: candidate

## Name and version
- Experiment: `EXP_behavioral_default_v1`
- Model: `MODEL_behavioral_default_v1`
- Feature registry: v1.0.0

## Purpose
Behavioral early-warning model for next-month default

## Intended use
A technical/case-study diagnostic of a behavioral early-warning default model on a
historical public benchmark (UCI, Taiwan, 2005), demonstrating methodological rigor
(leakage controls, calibration, uncertainty, subgroup audit, robustness).

## Prohibited uses
- Credit-granting (origination) decisions - the dataset structurally does not support
  that framing (see `docs/target_and_leakage_audit.md`).
- Automated approve/reject, pricing, credit-limit decisions.
- Regulatory PD, LGD, EAD, profit optimization.
- Any legal/fair-lending compliance claim.
- **Not suitable for real lending decisions.**

## Dataset
- Source: `uci-default-credit` (hash `45bcf4df62ff2e23...`)
- Population: Taiwanese credit card clients, 2005 (not a Brazilian population).
- Observed prevalence: 0.221167

## Target
Column `Y` - default in the month following the 6-month window.

## Split
Combined split hash: `4022f9cc24a66c25...` (seed=42, stratified 60/20/20).

## Features
18 engineered behavioral features (see
`config/modeling/feature_registry.yml`) - no demographic attribute used in training.

## Excluded attributes
SEX, EDUCATION, MARRIAGE, AGE - post-hoc audit only
(`credlens.modeling.subgroup_audit`).

## Models and selection
logistic_regression (main) / hist_gradient_boosting (challenger). Full comparison in `reports/modeling/tables/EXP_behavioral_default_v1__champion_challenger.csv`.

## Metrics (locked test set)
- ROC-AUC: 0.745123
- PR-AUC: 0.501927
- KS: 0.386644
- Brier: 0.142587
- Calibration slope/intercept: 0.947505 / -0.045965

## Calibration
Selected method: `none`. No calibration method produced a consistent improvement over the uncalibrated model on validation (best Brier 0.141257 vs. uncalibrated 0.141384) - the uncalibrated model is preserved.

## Thresholds
Illustrative review-capacity scenario (never profit-optimized)

## Uncertainty
See `reports/modeling/tables/EXP_behavioral_default_v1__bootstrap.json` (stratified bootstrap) and
`EXP_behavioral_default_v1__split_stability.csv` (multiple split seeds).

## Subgroup audit
See "Fairness and subgroup diagnostics - not a compliance assessment" in
`reports/modeling/tables/EXP_behavioral_default_v1__subgroup_audit.csv`. Not a fairness
certification, not a legal compliance assessment.

## Interpretability
Coefficients/odds ratios, permutation importance, partial dependence, and descriptive
reason codes - see `reports/modeling/tables/EXP_behavioral_default_v1__coefficients.csv`,
`EXP_behavioral_default_v1__permutation_importance.csv`, `EXP_behavioral_default_v1__local_explanations.json`.

## Robustness
See `reports/modeling/tables/EXP_behavioral_default_v1__robustness.csv` - technical perturbation
tests, not a real-crisis forecast.

## Limitations
- Historical public benchmark (UCI, Taiwan, 2005) - not a Brazilian population.
- Behavioral early-warning model for an existing account - not an origination score.
- Not suitable for real lending decisions.

## Risks
Historical dataset from a different country/era; risk of improper generalization to the
CredLens synthetic portfolio or to any real institution.

## Governance
This model was trained on a historical public benchmark and is not connected to the synthetic CredLens portfolio.

## Reproduction
`uv run credlens model train/evaluate/explain/audit-groups/stress-test/register/report`
with the same `--experiment-id` and seed.

## Future maintenance
No automatic promotion to "champion"/"production". Mandatory re-evaluation if the
feature registry, target contract, or source dataset version changes.

**Not suitable for real lending decisions.**
