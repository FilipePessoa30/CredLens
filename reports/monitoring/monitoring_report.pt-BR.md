# Relatório de Monitoramento (Fase 9)

**Simulação de monitoramento sobre um benchmark público histórico**

Esta é uma demonstração de METODOLOGIA de monitoramento, não um sistema de monitoramento de produção real - os batches são partições simuladas de um benchmark histórico, nunca dados reais de produção com data real.

## Execução
`RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728` - referência `REF_TEST_cli9_model`,
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
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0151 | 1 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0152 | 1 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0153 | 1 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0154 | 2 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0155 | 2 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0156 | 3 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0157 | 3 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0158 | 3 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0159 | 3 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0160 | 3 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0161 | 3 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0162 | 3 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0163 | 3 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0164 | 3 | high | feature_drift | psi__limit_exposure_distance | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0165 | 4 | medium | feature_drift | psi__bill_trend | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0166 | 4 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0167 | 4 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0168 | 4 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0169 | 4 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0170 | 5 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0171 | 5 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0172 | 5 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0173 | 5 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0174 | 5 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0175 | 5 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0176 | 5 | high | performance_drift | roc_auc_delta | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0177 | 6 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0178 | 6 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0179 | 6 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0180 | 6 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0181 | 6 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0182 | 6 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0183 | 6 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0184 | 6 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0185 | 7 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0186 | 7 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0187 | 7 | medium | feature_drift | psi__utilization_ratio | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0188 | 7 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0189 | 7 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0190 | 7 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0191 | 8 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0192 | 8 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0193 | 8 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0194 | 8 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0195 | 8 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0196 | 9 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0197 | 9 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0198 | 9 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0199 | 9 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0200 | 9 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0201 | 9 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0202 | 9 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0203 | 9 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0204 | 9 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0205 | 9 | high | feature_drift | psi__limit_exposure_distance | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0206 | 9 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0207 | 10 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0208 | 10 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0209 | 10 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0210 | 10 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0211 | 10 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0212 | 10 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0213 | 10 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0214 | 10 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0215 | 10 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0216 | 10 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0217 | 10 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0218 | 10 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0219 | 10 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0220 | 10 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0221 | 10 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0222 | 11 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0223 | 11 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0224 | 11 | medium | score_drift | score_mean_shift | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260803T035728_0225 | 12 | high | data_quality | schema_validity | blocked_input |

## Taxa de falso alerta (batch baseline-like)
0.1429

## Limitações
Batches simulados a partir do conjunto de teste bloqueado da UCI, particionado por ID - nunca datas
reais de produção. Ações diagnósticas são sugestões, nunca decisões automáticas.
