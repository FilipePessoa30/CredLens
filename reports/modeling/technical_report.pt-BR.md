# Relatório Técnico - Modelo Comportamental de Alerta Antecipado (Phase 8)

## 1. Problema
Modelo comportamental de alerta antecipado para inadimplência no mês seguinte

## 2. Fonte
`uci-default-credit`, hash `45bcf4df62ff2e237a74eb155cabfb4bbbc171219a0637daef44fdad07503dd0`.

## 3. Auditoria
Ver `reports/data_audit/` (Phase 2) e `credlens model data-audit` (reprodução).

## 4. Target
Coluna `Y`, ver `config/modeling/behavioral_default.yml`.

## 5. Features
max_delinquency_status, months_delinquent_count, most_recent_delinquency_status, delinquency_trend, consecutive_months_delinquent, total_bill_amount, avg_bill_amount, bill_trend, bill_variability, utilization_ratio, total_payment_amount, avg_payment_amount, payment_to_bill_ratio, months_without_payment, payment_coverage_rate, payment_variation, worst_payment_to_bill_ratio, limit_exposure_distance

## 6. Controles de leakage
| Controle | Passou | Detalhe |
|---|---|---|
| reject_direct_target_column | True | static allowlist rejected the raw target |
| reject_target_copy_feature | True | static allowlist rejected a renamed target copy |
| near_perfect_leakage_is_detectable | True | ROC-AUC with an injected near-perfect-leak column = 1.0000 (never added to the real allowlisted training frame) |
| shuffled_target_scores_near_random | True | ROC-AUC with a shuffled target = 0.4192 (within 0.12 of random, 0.5, required) |
| id_only_model_carries_no_signal | True | ROC-AUC using ONLY the record identifier as a feature = 0.5090 |

## 7. Split
Seed 42, hash combinado `4022f9cc24a66c2510823e06bd0334d7e4b89afe35eb5b6e0dfba76377351d94`.

## 8. Baselines, 9. Tuning, 10. Calibração
Estimador principal: logistic_regression (main) / hist_gradient_boosting (challenger). Hiperparâmetros: {"C": 0.1}.
Calibração: none.

## 11. Avaliação (teste bloqueado) / 12. Operating points / 13. Incerteza
Ver tabelas `reports/modeling/tables/TEST_cli_pipeline__*.csv` e
`TEST_cli_pipeline__bootstrap.json`.

## 14. Interpretabilidade / 15. Diagnóstico de subgrupo / 16. Robustez
Ver `TEST_cli_pipeline__coefficients.csv`, `TEST_cli_pipeline__subgroup_audit.csv`,
`TEST_cli_pipeline__robustness.csv`.

## 17. Comparação champion/challenger
| Modelo | ROC-AUC | PR-AUC | Brier | KS |
|---|---|---|---|---|
| dummy_prior | 0.5 | 0.221167 | 0.172252 | 0.0 |
| simple_rule | 0.702778 | 0.386911 | 0.149782 | 0.375813 |
| logistic_regression | 0.745123 | 0.501927 | 0.142587 | 0.386644 |
| hist_gradient_boosting | 0.780058 | 0.561983 | 0.134404 | 0.431741 |

## 18. Gates de registro
| Gate | Passou | Detalhe |
|---|---|---|
| beats_dummy_baseline_pr_auc | True | candidate PR-AUC 0.5019 vs. dummy 0.2212 |
| beats_simple_rule_baseline_pr_auc | True | candidate PR-AUC 0.5019 vs. simple rule 0.3869 |
| meets_minimum_test_roc_auc | True | candidate ROC-AUC 0.7451 vs. minimum 0.6 |
| no_leakage_detected | True | static + negative-control checks |
| calibration_acceptable | True | calibration comparison completed |
| stable_across_split_seeds | True | ROC-AUC stdev across seeds 0.0088 vs. max 0.02 |
| subgroup_audit_completed | True | post-hoc subgroup audit ran |
| artifact_validated | True | input/output schema validation |

**Resultado**: All gates passed - eligible for candidate registration.

## 19. Limitações
Este modelo foi treinado em um benchmark público histórico e não está conectado ao portfólio sintético do CredLens. Não é adequado para decisões reais de concessão de crédito.

## 20. Reprodução
`uv run credlens model train --experiment-id TEST_cli_pipeline --seed 42`, seguido de
`evaluate`, `compare`, `explain`, `audit-groups`, `stress-test`, `register`, `report`.
