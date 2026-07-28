# Monitoring Report (Phase 9)

**Monitoring simulation on a historical public benchmark**

This is a demonstration of monitoring METHODOLOGY, not a real production monitoring system - batches are simulated partitions of a historical benchmark, never real dated production data.

## Run
`RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201` - reference `REF_TEST_cli9_model`,
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
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0001 | 1 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0002 | 1 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0003 | 1 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0004 | 2 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0005 | 2 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0006 | 3 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0007 | 3 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0008 | 3 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0009 | 3 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0010 | 3 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0011 | 3 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0012 | 3 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0013 | 3 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0014 | 3 | high | feature_drift | psi__limit_exposure_distance | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0015 | 3 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0016 | 4 | medium | feature_drift | psi__bill_trend | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0017 | 4 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0018 | 4 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0019 | 4 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0020 | 4 | high | performance_drift | roc_auc_delta | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0021 | 5 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0022 | 5 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0023 | 5 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0024 | 5 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0025 | 5 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0026 | 5 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0027 | 5 | high | performance_drift | roc_auc_delta | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0028 | 6 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0029 | 6 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0030 | 6 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0031 | 6 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0032 | 6 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0033 | 6 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0034 | 6 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0035 | 6 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0036 | 7 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0037 | 7 | medium | feature_drift | psi__most_recent_delinquency_status | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0038 | 7 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0039 | 7 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0040 | 7 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0041 | 7 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0042 | 7 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0043 | 7 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0044 | 7 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0045 | 7 | high | feature_drift | psi__limit_exposure_distance | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0046 | 7 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0047 | 8 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0048 | 8 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0049 | 8 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0050 | 8 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0051 | 8 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0052 | 9 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0053 | 9 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0054 | 9 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0055 | 9 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0056 | 9 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0057 | 9 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0058 | 9 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0059 | 9 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0060 | 9 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0061 | 9 | high | feature_drift | psi__limit_exposure_distance | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0062 | 9 | high | score_drift | score_mean_shift | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0063 | 10 | high | feature_drift | psi__max_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0064 | 10 | high | feature_drift | psi__months_delinquent_count | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0065 | 10 | high | feature_drift | psi__most_recent_delinquency_status | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0066 | 10 | high | feature_drift | psi__delinquency_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0067 | 10 | high | feature_drift | psi__consecutive_months_delinquent | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0068 | 10 | high | feature_drift | psi__total_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0069 | 10 | high | feature_drift | psi__avg_bill_amount | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0070 | 10 | high | feature_drift | psi__bill_trend | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0071 | 10 | high | feature_drift | psi__bill_variability | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0072 | 10 | high | feature_drift | psi__utilization_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0073 | 10 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0074 | 10 | high | feature_drift | psi__payment_coverage_rate | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0075 | 10 | high | feature_drift | psi__payment_variation | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0076 | 10 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0077 | 10 | medium | performance_drift | roc_auc_delta | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0078 | 11 | high | feature_drift | psi__payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0079 | 11 | high | feature_drift | psi__worst_payment_to_bill_ratio | material_deviation |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0080 | 11 | medium | score_drift | score_mean_shift | review |
| ALERT_RUN_BATCHSET_REF_TEST_cli9_model_20260728T194201_0081 | 12 | high | data_quality | schema_validity | blocked_input |

## False-alert rate (baseline-like batch)
0.1429

## Limitations
Batches are simulated partitions of the UCI locked test set, sliced by ID - never real dated
production data. Diagnostic actions are suggestions, never automated decisions.
