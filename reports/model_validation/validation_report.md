# Independent Validation Report (Phase 9)

## 1. Scope and independence
This report is produced by `credlens.model_validation`, a package separate from
`credlens.modeling` (Phase 8). Every metric here is recomputed with an independent
implementation from FROZEN evidence (`reports/model_validation/evidence/`), never copied from
the original Phase 8 report.

## 2. Audited experiment
`EXP_behavioral_default_v1`

## 3. Validation gates (14)
| Gate | Status | Severity | Result | Justification |
|---|---|---|---|---|
| dataset_integrity | pass | blocking | OK | evidence.dataset_hash=45bcf4df62ff2e23... |
| split_integrity | pass | blocking | OK | recomputed split hash matches experiment record (4022f9cc24a66c25...) |
| leakage | pass | blocking | OK | experiment.warnings=[] |
| negative_controls | pass | blocking | OK | Control 1 (score-label): Real ROC-AUC (0.7503) exceeds 99/99 label permutations (empirical p=0.0100); null mean 0.4997 (z=-0.41) and std 0.00837 (ratio to theory=0.93) both within expectation. | Control 2 (pipeline retrain): Real model validation ROC-AUC (0.7503) exceeds 99/99 permuted-target refits (empirical p=0.0100); null mean 0.4897 (z=-1.35) is centered. Observed std 0.07604 is wider than Control 1's theoretical label-permutation-only SE (0.00898) - expected, since this control's variance includes model-refitting noise (see module docstring). |
| discrimination | pass | blocking | OK | 3 metric(s) recomputed within tolerance |
| calibration | pass | blocking | OK | 5 calibration metric(s) recomputed within tolerance |
| stability | pass | blocking | OK | roc_auc_stdev=0.0088 |
| coefficient_stability | warning | non_blocking | LIMITATION | unstable/redundant features: ['months_delinquent_count', 'consecutive_months_delinquent', 'avg_payment_amount', 'total_payment_amount', 'avg_bill_amount', 'total_bill_amount', 'bill_trend', 'bill_variability', 'worst_payment_to_bill_ratio'] |
| subgroup_audit | pass | non_blocking | OK | max selection-rate absolute_gap=0.0530 |
| robustness | pass | blocking | OK | 2 spot-checked perturbation(s) reproduced |
| input_contract | pass | blocking | OK | strict-mode self-test rejected every injected violation type |
| artifact_integrity | pass | blocking | OK | validate_model_candidate hash-verified and scored a probe row |
| reproducibility | pass | blocking | OK | predictions_test.csv hash matches the frozen evidence manifest. |
| documentation | pass | blocking | OK | model_card.md/.pt-BR.md/technical_report.md present with mandatory disclosures. |

## 4. Final decision
**validation_passed_with_limitations**

All blocking gates passed; non-blocking gate(s) raised limitations: coefficient_stability.

## 5. Limitations
Historical public benchmark (UCI, Taiwan, 2005). This independent validation is not a fairness
certification, not a legal compliance assessment, and not an approval for use in real lending
decisions. **Not suitable for real lending decisions.**
