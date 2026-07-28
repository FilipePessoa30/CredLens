"""Tests for credlens.dashboard.monitoring_charts (Phase 9 section 22):
every chart degrades to an empty (but valid) figure for empty/missing
input, and real precomputed batch/alert data produces real traces.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from credlens.dashboard import monitoring_charts as charts

_BATCH = {
    "batch_sequence": 1,
    "simulation_scenario": "baseline_like",
    "data_quality": {
        "missingness_rate": 0.01,
        "domain_violation_rate": 0.0,
        "range_violation_rate": 0.0,
        "duplicate_rate": 0.0,
    },
    "feature_drift": [
        {
            "feature": "max_delinquency_status",
            "psi": 0.02,
            "ks_statistic": 0.05,
            "wasserstein_distance": 0.1,
            "jensen_shannon_divergence": 0.01,
        },
        {
            "feature": "utilization_ratio",
            "psi": 0.03,
            "ks_statistic": 0.06,
            "wasserstein_distance": 0.2,
            "jensen_shannon_divergence": 0.02,
        },
    ],
    "score_drift": {
        "batch_mean_score": 0.25,
        "reference_mean_score": 0.22,
        "risk_band_distribution": {"low": 0.5, "medium": 0.3, "high": 0.15, "very_high": 0.05},
    },
    "performance_drift": {
        "roc_auc": 0.74,
        "pr_auc": 0.5,
        "calibration_slope": 0.95,
        "calibration_intercept": -0.05,
    },
    "subgroup_monitoring": [
        {
            "attribute": "sex",
            "group": "male",
            "composition_share": 0.5,
            "reference_composition_share": 0.48,
            "selection_rate": 0.12,
        },
        {
            "attribute": "sex",
            "group": "female",
            "composition_share": 0.5,
            "reference_composition_share": 0.52,
            "selection_rate": 0.10,
        },
    ],
}

_ALERT = {
    "alert_id": "ALERT_1",
    "batch_sequence": 1,
    "severity": "high",
    "category": "feature_drift",
    "metric": "psi__a",
    "status": "material_deviation",
}


class TestEmptyInputsNeverRaise:
    def test_data_quality_status_chart_empty(self) -> None:
        assert isinstance(charts.data_quality_status_chart([]), go.Figure)

    def test_feature_drift_heatmap_chart_empty(self) -> None:
        assert isinstance(charts.feature_drift_heatmap_chart([]), go.Figure)

    def test_psi_ks_wasserstein_chart_empty(self) -> None:
        assert isinstance(charts.psi_ks_wasserstein_chart([], "some_feature"), go.Figure)

    def test_score_distribution_chart_empty(self) -> None:
        assert isinstance(charts.score_distribution_chart([]), go.Figure)

    def test_risk_band_shift_chart_empty(self) -> None:
        assert isinstance(charts.risk_band_shift_chart([]), go.Figure)

    def test_performance_over_batches_chart_empty(self) -> None:
        assert isinstance(charts.performance_over_batches_chart([]), go.Figure)

    def test_calibration_over_batches_chart_empty(self) -> None:
        assert isinstance(charts.calibration_over_batches_chart([]), go.Figure)

    def test_subgroup_composition_chart_empty(self) -> None:
        assert isinstance(charts.subgroup_composition_chart(None), go.Figure)

    def test_subgroup_gaps_chart_empty(self) -> None:
        assert isinstance(charts.subgroup_gaps_chart([]), go.Figure)

    def test_alert_timeline_chart_empty(self) -> None:
        assert isinstance(charts.alert_timeline_chart([]), go.Figure)

    def test_validation_gates_chart_empty(self) -> None:
        assert isinstance(charts.validation_gates_chart([]), go.Figure)

    def test_pareto_tradeoff_chart_empty(self) -> None:
        assert isinstance(charts.pareto_tradeoff_chart(pd.DataFrame()), go.Figure)


class TestRealDataProducesTraces:
    def test_data_quality_status_chart_real(self) -> None:
        fig = charts.data_quality_status_chart([_BATCH])
        assert len(fig.data) == 4

    def test_feature_drift_heatmap_chart_real(self) -> None:
        fig = charts.feature_drift_heatmap_chart([_BATCH])
        assert len(fig.data) == 1

    def test_psi_ks_wasserstein_chart_real(self) -> None:
        fig = charts.psi_ks_wasserstein_chart([_BATCH], "max_delinquency_status")
        assert len(fig.data) == 3

    def test_score_distribution_chart_real(self) -> None:
        fig = charts.score_distribution_chart([_BATCH])
        assert len(fig.data) == 2

    def test_risk_band_shift_chart_real(self) -> None:
        fig = charts.risk_band_shift_chart([_BATCH])
        assert len(fig.data) == 4

    def test_performance_over_batches_chart_real(self) -> None:
        fig = charts.performance_over_batches_chart([_BATCH])
        assert len(fig.data) == 2

    def test_subgroup_composition_chart_real(self) -> None:
        fig = charts.subgroup_composition_chart(_BATCH, "sex")
        assert len(fig.data) == 2

    def test_subgroup_gaps_chart_real(self) -> None:
        fig = charts.subgroup_gaps_chart([_BATCH])
        assert len(fig.data) == 1

    def test_alert_timeline_chart_real(self) -> None:
        fig = charts.alert_timeline_chart([_ALERT])
        assert len(fig.data) == 1

    def test_validation_gates_chart_real(self) -> None:
        gates = [{"name": "g1", "status": "pass"}, {"name": "g2", "status": "warning"}]
        fig = charts.validation_gates_chart(gates)
        assert len(fig.data) == 1

    def test_pareto_tradeoff_chart_real(self) -> None:
        table = pd.DataFrame(
            {"model": ["a", "b"], "scoring_latency_ms": [1.0, 5.0], "pr_auc": [0.5, 0.56]}
        )
        fig = charts.pareto_tradeoff_chart(table)
        assert len(fig.data) == 1
