# Remediation Report (Phase 10 gate D)

## 1. Scope
Post-validation remediation of `EXP_behavioral_default_v1`'s redundant/unstable logistic
regression coefficients. Never overwrites `EXP_behavioral_default_v1`/
`MODEL_behavioral_default_v1`. Feature-selection decisions are documented in
`config/model_validation/remediation_policy.yml`.

## 2. Holdout reuse
Per gate C, this is a **post-validation remediation model**, never a new independent
external validation - the frozen test set has already been repeatedly observed across
Phases 8-10. See `reports/model_validation/validation_report.md` section 6 for the full
disclosure.

## 3. Five-model comparison
New experiment: `TEST_cli10_remediated`.

| Model | Features | PR-AUC | ROC-AUC | Brier | Max VIF | Sign-flip | Split-stability std | Reason-code features |
|---|---|---|---|---|---|---|---|---|
| original logistic (v1) | 18 | 0.5019 | 0.7451 | 0.1426 | 56.83 | 0.0761 | 0.008841 | 7 |
| VIF-reduced | 14 | 0.4995 | 0.7405 | 0.1434 | n/a | n/a | 0.008265 | n/a |
| Stability-reduced (mechanical) | 9 | 0.4928 | 0.7246 | 0.1452 | 17073.31 | 0.0094 | 0.008901 | 5 |
| Final remediated (gate D) | 11 | 0.5016 | 0.7423 | 0.1429 | 7.05 | 0.0132 | 0.007577 | 9 |
| HistGBM (challenger) | 18 | 0.5620 | 0.7801 | 0.1344 | n/a | n/a | 0.007632 | n/a |

## 4. Decision
**remediation_candidate**

Remediation resolved the structural problems (max VIF 7.046, mean sign-flip rate 0.0132) while keeping PR-AUC/ROC-AUC within -0.0004/-0.0028 of v1 - a plausible, non-suspicious change. Never auto-promoted: v1 remains the official model; this is a post-validation remediation model requiring its own explicit registration.

## 5. Registration
Registered as `TEST_cli10_remediated_model` (status=`remediation_candidate`).

## 6. Limitations
Historical public benchmark (UCI, Taiwan, 2005). Not a fairness certification, not a legal
compliance assessment. **Not suitable for real lending decisions.**
