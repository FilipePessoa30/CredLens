# Relatório de Monitoramento (Fase 9)

**Simulação de monitoramento sobre um benchmark público histórico**

Esta é uma demonstração de METODOLOGIA de monitoramento, não um sistema de monitoramento de produção real - os batches são partições simuladas de um benchmark histórico, nunca dados reais de produção com data real.

## Execução
`RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104` - referência `REF_TEST_cli9_model`,
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
| 7 | feature_range_violation | available | scored | 500 | 0 |
| 8 | prevalence_drift | available | scored | 311 | 0 |
| 9 | score_distribution_shift | available | scored | 500 | 0 |
| 10 | subgroup_composition_shift | available | scored | 500 | 89 |
| 11 | label_delay | pending | scored | 500 | 0 |
| 12 | corrupted_schema | available | blocked | 500 | 500 |

## Alertas (80)
| Alert ID | Batch | Severidade | Categoria | Métrica | Status |
|---|---|---|---|---|---|
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0445 | 1 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0446 | 1 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0447 | 1 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0448 | 2 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0449 | 2 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0450 | 3 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0451 | 3 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0452 | 3 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0453 | 3 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0454 | 3 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0455 | 3 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0456 | 3 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0457 | 3 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0458 | 3 | high | feature_drift | psi__limit_exposure_distance | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0459 | 4 | medium | feature_drift | psi__bill_trend | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0460 | 4 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0461 | 4 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0462 | 4 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0463 | 4 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0464 | 5 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0465 | 5 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0466 | 5 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0467 | 5 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0468 | 5 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0469 | 5 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0470 | 5 | high | performance_drift | roc_auc_delta | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0471 | 6 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0472 | 6 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0473 | 6 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0474 | 6 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0475 | 6 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0476 | 6 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0477 | 6 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0478 | 6 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0479 | 7 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0480 | 7 | medium | feature_drift | psi__most_recent_delinquency_status | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0481 | 7 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0482 | 7 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0483 | 7 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0484 | 7 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0485 | 7 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0486 | 7 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0487 | 7 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0488 | 7 | high | feature_drift | psi__limit_exposure_distance | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0489 | 7 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0490 | 8 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0491 | 8 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0492 | 8 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0493 | 8 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0494 | 8 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0495 | 9 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0496 | 9 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0497 | 9 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0498 | 9 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0499 | 9 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0500 | 9 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0501 | 9 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0502 | 9 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0503 | 9 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0504 | 9 | high | feature_drift | psi__limit_exposure_distance | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0505 | 9 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0506 | 10 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0507 | 10 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0508 | 10 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0509 | 10 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0510 | 10 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0511 | 10 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0512 | 10 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0513 | 10 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0514 | 10 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0515 | 10 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0516 | 10 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0517 | 10 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0518 | 10 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0519 | 10 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0520 | 10 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0521 | 11 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0522 | 11 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0523 | 11 | medium | score_drift | score_mean_shift | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260801T033104_0524 | 12 | high | data_quality | schema_validity | blocked_input |

## Taxa de falso alerta (batch baseline-like)
0.1429

## Limitações
Batches simulados a partir do conjunto de teste bloqueado da UCI, particionado por ID - nunca datas
reais de produção. Ações diagnósticas são sugestões, nunca decisões automáticas.
