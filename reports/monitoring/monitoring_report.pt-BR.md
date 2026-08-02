# Relatório de Monitoramento (Fase 9)

**Simulação de monitoramento sobre um benchmark público histórico**

Esta é uma demonstração de METODOLOGIA de monitoramento, não um sistema de monitoramento de produção real - os batches são partições simuladas de um benchmark histórico, nunca dados reais de produção com data real.

## Execução
`RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255` - referência `REF_TEST_cli9_model`,
conjunto de batches `BATCHSET_REF_TEST_cli9_model`, modelo `TEST_cli9_model`.

## Batches simulados
| Sequência | Cenário | Rótulos | Status | Linhas | Quarentena |
|---|---|---|---|---|---|
| 1 | baseline_like | available | scored | 500 | 0 |
| 2 | missingness_drift | available | scored | 500 | 73 |
| 3 | utilization_shift | available | scored | 500 | 0 |
| 4 | payment_reduction | available | scored | 500 | 0 |
| 5 | delinquency_worsening | available | scored | 500 | 0 |
| 6 | out_of_domain_codes | available | scored | 500 | 238 |
| 7 | feature_range_violation | available | scored | 500 | 11 |
| 8 | prevalence_drift | available | scored | 311 | 0 |
| 9 | score_distribution_shift | available | scored | 500 | 0 |
| 10 | subgroup_composition_shift | available | scored | 500 | 89 |
| 11 | label_delay | pending | scored | 500 | 0 |
| 12 | corrupted_schema | available | blocked | 500 | 500 |

## Alertas (75)
| Alert ID | Batch | Severidade | Categoria | Métrica | Status |
|---|---|---|---|---|---|
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0001 | 1 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0002 | 1 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0003 | 1 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0004 | 2 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0005 | 2 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0006 | 3 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0007 | 3 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0008 | 3 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0009 | 3 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0010 | 3 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0011 | 3 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0012 | 3 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0013 | 3 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0014 | 3 | high | feature_drift | psi__limit_exposure_distance | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0015 | 4 | medium | feature_drift | psi__bill_trend | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0016 | 4 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0017 | 4 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0018 | 4 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0019 | 4 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0020 | 5 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0021 | 5 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0022 | 5 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0023 | 5 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0024 | 5 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0025 | 5 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0026 | 5 | high | performance_drift | roc_auc_delta | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0027 | 6 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0028 | 6 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0029 | 6 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0030 | 6 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0031 | 6 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0032 | 6 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0033 | 6 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0034 | 6 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0035 | 7 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0036 | 7 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0037 | 7 | medium | feature_drift | psi__utilization_ratio | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0038 | 7 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0039 | 7 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0040 | 7 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0041 | 8 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0042 | 8 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0043 | 8 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0044 | 8 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0045 | 8 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0046 | 9 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0047 | 9 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0048 | 9 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0049 | 9 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0050 | 9 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0051 | 9 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0052 | 9 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0053 | 9 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0054 | 9 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0055 | 9 | high | feature_drift | psi__limit_exposure_distance | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0056 | 9 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0057 | 10 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0058 | 10 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0059 | 10 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0060 | 10 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0061 | 10 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0062 | 10 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0063 | 10 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0064 | 10 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0065 | 10 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0066 | 10 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0067 | 10 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0068 | 10 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0069 | 10 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0070 | 10 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0071 | 10 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0072 | 11 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0073 | 11 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0074 | 11 | medium | score_drift | score_mean_shift | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260802T212255_0075 | 12 | high | data_quality | schema_validity | blocked_input |

## Taxa de falso alerta (batch baseline-like)
0.1429

## Limitações
Batches simulados a partir do conjunto de teste bloqueado da UCI, particionado por ID - nunca datas
reais de produção. Ações diagnósticas são sugestões, nunca decisões automáticas.
