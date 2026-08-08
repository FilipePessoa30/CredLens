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
| negative_controls | pass | blocking | OK | Control 1 (score-label): Real ROC-AUC (0.7503) exceeds 999/999 label permutations (empirical p=0.0010); null mean 0.5000 (z=0.14) and std 0.00887 (ratio to theory=0.99) both within expectation. | Control 2 (pipeline retrain): Real model validation ROC-AUC (0.7503) exceeds 100/100 permuted-target refits (empirical p=0.0099); null mean 0.4907 (z=-1.22) is centered. Observed std 0.07633 is wider than Control 1's theoretical label-permutation-only SE (0.00898) - expected, since this control's variance includes model-refitting noise (see module docstring). |
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

## 6. Holdout reuse disclosure
**Frozen evaluation holdout reused across documented validation phases.**

The train/validation/test split (`split_assignment.csv`) has never been altered since it was
created in Phase 8. The original test predictions (`predictions_test.csv`) remain frozen - no
original hyperparameter tuning, feature selection, or threshold decision ever used the test set.
That said, this same test set has been repeatedly consulted across Phases 8-10 for: candidate
model comparison, discrimination/calibration metric computation, robustness analysis, subgroup
auditing, threshold validation, and candidate/challenger comparison. Each consultation observed
(without retraining on) the test set's results. For that reason, this report deliberately does
NOT describe the holdout as "untouched" or "opened only once" - that description stopped being
accurate. Any NEW model created after these repeated observations (for example, a Phase 10
remediated regression) carries an indirect-adaptation risk: even without directly retraining on
the test set, human design decisions may have been shaped by results already observed on it. No
second, independent external holdout exists in this project. Any remediated model is called a
**"post-validation remediation model"**, never a new independent external validation.
