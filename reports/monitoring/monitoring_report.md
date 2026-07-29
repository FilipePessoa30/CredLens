# Monitoring Report (Phase 9)

**Monitoring simulation on a historical public benchmark**

This is a demonstration of monitoring METHODOLOGY, not a real production monitoring system - batches are simulated partitions of a historical benchmark, never real dated production data.

## Run
`RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903` - reference `REF_TEST_cli9_model`,
batch set `BATCHSET_REF_TEST_cli9_model`, model `TEST_cli9_model`.

## Simulated batches
| Sequence | Scenario | Labels | Status | Rows | Quarantined |
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

## Alerts (81)
| Alert ID | Batch | Severity | Category | Metric | Status |
|---|---|---|---|---|---|
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0001 | 1 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0002 | 1 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0003 | 1 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0004 | 2 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0005 | 2 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0006 | 3 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0007 | 3 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0008 | 3 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0009 | 3 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0010 | 3 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0011 | 3 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0012 | 3 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0013 | 3 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0014 | 3 | high | feature_drift | psi__limit_exposure_distance | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0015 | 3 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0016 | 4 | medium | feature_drift | psi__bill_trend | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0017 | 4 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0018 | 4 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0019 | 4 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0020 | 4 | high | performance_drift | roc_auc_delta | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0021 | 5 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0022 | 5 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0023 | 5 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0024 | 5 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0025 | 5 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0026 | 5 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0027 | 5 | high | performance_drift | roc_auc_delta | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0028 | 6 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0029 | 6 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0030 | 6 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0031 | 6 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0032 | 6 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0033 | 6 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0034 | 6 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0035 | 6 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0036 | 7 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0037 | 7 | medium | feature_drift | psi__most_recent_delinquency_status | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0038 | 7 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0039 | 7 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0040 | 7 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0041 | 7 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0042 | 7 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0043 | 7 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0044 | 7 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0045 | 7 | high | feature_drift | psi__limit_exposure_distance | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0046 | 7 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0047 | 8 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0048 | 8 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0049 | 8 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0050 | 8 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0051 | 8 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0052 | 9 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0053 | 9 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0054 | 9 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0055 | 9 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0056 | 9 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0057 | 9 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0058 | 9 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0059 | 9 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0060 | 9 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0061 | 9 | high | feature_drift | psi__limit_exposure_distance | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0062 | 9 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0063 | 10 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0064 | 10 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0065 | 10 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0066 | 10 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0067 | 10 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0068 | 10 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0069 | 10 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0070 | 10 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0071 | 10 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0072 | 10 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0073 | 10 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0074 | 10 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0075 | 10 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0076 | 10 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0077 | 10 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0078 | 11 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0079 | 11 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0080 | 11 | medium | score_drift | score_mean_shift | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260729T183903_0081 | 12 | high | data_quality | schema_validity | blocked_input |

## False-alert rate (baseline-like batch)
0.1429

## Limitations
Batches are simulated partitions of the UCI locked test set, sliced by ID - never real dated
production data. Diagnostic actions are suggestions, never automated decisions.
