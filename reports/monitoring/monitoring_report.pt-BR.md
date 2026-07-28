# Relatório de Monitoramento (Fase 9)

**Simulação de monitoramento sobre um benchmark público histórico**

Esta é uma demonstração de METODOLOGIA de monitoramento, não um sistema de monitoramento de produção real - os batches são partições simuladas de um benchmark histórico, nunca dados reais de produção com data real.

## Execução
`RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316` - referência `REF_MODEL_behavioral_default_v1`,
conjunto de batches `BATCHSET_REF_MODEL_behavioral_default_v1`, modelo `MODEL_behavioral_default_v1`.

## Batches simulados
| Sequência | Cenário | Rótulos | Status | Linhas | Quarentena |
|---|---|---|---|---|---|
| 1 | baseline_like | available | scored | 500 | 0 |
| 2 | missingness_drift | available | scored | 500 | 73 |
| 3 | utilization_shift | available | scored | 500 | 0 |
| 4 | payment_reduction | available | scored | 500 | 0 |
| 5 | delinquency_worsening | available | scored | 500 | 0 |
| 6 | out_of_domain_codes | available | scored | 500 | 238 |
| 7 | feature_range_violation | available | scored | 500 | 0 |
| 8 | prevalence_drift | available | scored | 311 | 0 |
| 9 | score_distribution_shift | available | scored | 500 | 0 |
| 10 | subgroup_composition_shift | available | scored | 500 | 89 |
| 11 | label_delay | pending | scored | 500 | 0 |
| 12 | corrupted_schema | available | blocked | 500 | 500 |

## Alertas (81)
| Alert ID | Batch | Severidade | Categoria | Métrica | Status |
|---|---|---|---|---|---|
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0001 | 1 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0002 | 1 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0003 | 1 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0004 | 2 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0005 | 2 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0006 | 3 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0007 | 3 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0008 | 3 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0009 | 3 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0010 | 3 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0011 | 3 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0012 | 3 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0013 | 3 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0014 | 3 | high | feature_drift | psi__limit_exposure_distance | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0015 | 3 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0016 | 4 | medium | feature_drift | psi__bill_trend | review |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0017 | 4 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0018 | 4 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0019 | 4 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0020 | 4 | high | performance_drift | roc_auc_delta | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0021 | 5 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0022 | 5 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0023 | 5 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0024 | 5 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0025 | 5 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0026 | 5 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0027 | 5 | high | performance_drift | roc_auc_delta | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0028 | 6 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0029 | 6 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0030 | 6 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0031 | 6 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0032 | 6 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0033 | 6 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0034 | 6 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0035 | 6 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0036 | 7 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0037 | 7 | medium | feature_drift | psi__most_recent_delinquency_status | review |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0038 | 7 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0039 | 7 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0040 | 7 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0041 | 7 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0042 | 7 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0043 | 7 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0044 | 7 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0045 | 7 | high | feature_drift | psi__limit_exposure_distance | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0046 | 7 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0047 | 8 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0048 | 8 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0049 | 8 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0050 | 8 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0051 | 8 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0052 | 9 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0053 | 9 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0054 | 9 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0055 | 9 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0056 | 9 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0057 | 9 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0058 | 9 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0059 | 9 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0060 | 9 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0061 | 9 | high | feature_drift | psi__limit_exposure_distance | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0062 | 9 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0063 | 10 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0064 | 10 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0065 | 10 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0066 | 10 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0067 | 10 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0068 | 10 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0069 | 10 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0070 | 10 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0071 | 10 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0072 | 10 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0073 | 10 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0074 | 10 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0075 | 10 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0076 | 10 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0077 | 10 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0078 | 11 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0079 | 11 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0080 | 11 | medium | score_drift | score_mean_shift | review |
| ALERT_RUN_BATCHSET_REF_MODEL_behavioral_default_v1_20260728T173316_0081 | 12 | high | data_quality | schema_validity | blocked_input |

## Taxa de falso alerta (batch baseline-like)
0.1429

## Limitações
Batches simulados a partir do conjunto de teste bloqueado da UCI, particionado por ID - nunca datas
reais de produção. Ações diagnósticas são sugestões, nunca decisões automáticas.
