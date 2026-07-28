# Relatório de Validação Independente (Fase 9)

## 1. Escopo e independência
Este relatório é produzido por `credlens.model_validation`, um pacote separado de
`credlens.modeling` (Fase 8). Toda métrica aqui é recomputada com uma implementação
independente a partir de evidência CONGELADA (`reports/model_validation/evidence/`), nunca
copiada do relatório original da Fase 8.

## 2. Experimento auditado
`EXP_behavioral_default_v1`

## 3. Gates de validação (14)
| Gate | Status | Severidade | Resultado | Justificativa |
|---|---|---|---|---|
| dataset_integrity | pass | blocking | OK | evidence.dataset_hash=45bcf4df62ff2e23... |
| split_integrity | pass | blocking | OK | recomputed split hash matches experiment record (4022f9cc24a66c25...) |
| leakage | pass | blocking | OK | experiment.warnings=[] |
| negative_controls | pass | blocking | OK | Real model validation ROC-AUC (0.7503) exceeds 100/100 permuted-target fits (empirical p=0.0099 <= alpha=0.01); the permutation-null mean ROC-AUC (0.4907) is within 0.05 of random (0.5). |
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

## 4. Decisão final
**validation_passed_with_limitations**

All blocking gates passed; non-blocking gate(s) raised limitations: coefficient_stability.

## 5. Limitações
Benchmark público histórico (UCI, Taiwan, 2005). Esta validação independente não constitui
certificação de fairness, avaliação de conformidade legal, nem aprovação para uso em decisões
reais de crédito. **Não é adequado para decisões reais de concessão de crédito.**
