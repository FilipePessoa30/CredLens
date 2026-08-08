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

## 4. Decisão final
**validation_passed_with_limitations**

All blocking gates passed; non-blocking gate(s) raised limitations: coefficient_stability.

## 5. Limitações
Benchmark público histórico (UCI, Taiwan, 2005). Esta validação independente não constitui
certificação de fairness, avaliação de conformidade legal, nem aprovação para uso em decisões
reais de crédito. **Não é adequado para decisões reais de concessão de crédito.**

## 6. Divulgação de reutilização do holdout
**Holdout de avaliação congelado, reutilizado em fases documentadas de validação.**

O split treino/validação/teste (`split_assignment.csv`) nunca foi alterado desde sua criação na
Fase 8. As previsões originais do teste (`predictions_test.csv`) permanecem congeladas - nenhum
ajuste de hiperparâmetro, seleção de feature ou decisão de threshold originais usou o teste. Ainda
assim, este mesmo conjunto de teste foi consultado repetidamente ao longo das Fases 8-10 para:
comparação de modelos candidatos, cálculo de métricas de discriminação/calibração, análise de
robustez, auditoria de subgrupos, validação de threshold e comparação candidato/challenger. Cada
consulta observou (sem re-treinar sobre) os resultados do teste. Por isso, este relatório NÃO
descreve o holdout como "nunca tocado" ou "aberto uma única vez" - essa descrição deixou de ser
precisa. Qualquer modelo NOVO criado depois dessas observações repetidas (por exemplo, uma
regressão remediada da Fase 10) carrega um risco de adaptação indireta: mesmo sem re-treinar
diretamente sobre o teste, decisões de design humanas podem ter sido influenciadas por resultados
já observados nele. Não existe um segundo holdout externo independente neste projeto. Qualquer
modelo remediado é chamado de **"modelo de remediação pós-validação"**, nunca de uma nova
validação externa independente.
