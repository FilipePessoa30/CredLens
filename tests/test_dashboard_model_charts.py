"""Tests for credlens.dashboard.model_charts (Phase 8 section 29): every
chart degrades to an empty (but valid) figure for empty/missing input,
and real precomputed data produces real traces."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from credlens.dashboard import model_charts as charts


class TestEmptyInputsNeverRaise:
    def test_roc_curve_chart_empty(self) -> None:
        fig = charts.roc_curve_chart(pd.DataFrame({"y_true": [0, 1], "logit": [0.1, 0.9]}), [])
        assert isinstance(fig, go.Figure)

    def test_precision_recall_chart_empty(self) -> None:
        fig = charts.precision_recall_chart(pd.DataFrame({"y_true": [0, 1]}), [])
        assert isinstance(fig, go.Figure)

    def test_calibration_chart_missing_model_kind(self) -> None:
        fig = charts.calibration_chart(pd.DataFrame({"y_true": [0, 1]}), "logistic_regression")
        assert isinstance(fig, go.Figure)

    def test_decile_lift_chart_empty(self) -> None:
        fig = charts.decile_lift_chart([])
        assert isinstance(fig, go.Figure)

    def test_cumulative_gains_chart_empty(self) -> None:
        fig = charts.cumulative_gains_chart([])
        assert isinstance(fig, go.Figure)

    def test_event_rate_by_decile_chart_empty(self) -> None:
        fig = charts.event_rate_by_decile_chart([], 0.2)
        assert isinstance(fig, go.Figure)

    def test_champion_challenger_chart_empty(self) -> None:
        fig = charts.champion_challenger_chart(pd.DataFrame())
        assert isinstance(fig, go.Figure)

    def test_coefficients_chart_empty(self) -> None:
        fig = charts.coefficients_chart(pd.DataFrame())
        assert isinstance(fig, go.Figure)

    def test_permutation_importance_chart_empty(self) -> None:
        fig = charts.permutation_importance_chart(pd.DataFrame())
        assert isinstance(fig, go.Figure)

    def test_partial_dependence_chart_empty(self) -> None:
        fig = charts.partial_dependence_chart(pd.DataFrame(), "some_feature")
        assert isinstance(fig, go.Figure)

    def test_subgroup_chart_empty(self) -> None:
        fig = charts.subgroup_chart(pd.DataFrame())
        assert isinstance(fig, go.Figure)

    def test_robustness_chart_empty(self) -> None:
        fig = charts.robustness_chart(pd.DataFrame())
        assert isinstance(fig, go.Figure)

    def test_seed_stability_chart_empty(self) -> None:
        fig = charts.seed_stability_chart(pd.DataFrame())
        assert isinstance(fig, go.Figure)


class TestRealDataProducesTraces:
    def test_roc_curve_chart_with_real_predictions(self) -> None:
        predictions = pd.DataFrame(
            {"y_true": [0, 0, 1, 1], "logistic_regression": [0.1, 0.3, 0.7, 0.9]}
        )
        fig = charts.roc_curve_chart(predictions, ["logistic_regression"])
        assert len(fig.data) == 2  # model curve + random baseline

    def test_champion_challenger_chart_with_real_data(self) -> None:
        table = pd.DataFrame(
            {
                "model": ["dummy_prior", "logistic_regression"],
                "roc_auc": [0.5, 0.75],
                "pr_auc": [0.2, 0.5],
            }
        )
        fig = charts.champion_challenger_chart(table)
        assert len(fig.data) == 2

    def test_coefficients_chart_colors_by_sign(self) -> None:
        table = pd.DataFrame(
            {"feature": ["a", "b"], "coefficient": [1.0, -1.0], "odds_ratio": [2.7, 0.37]}
        )
        fig = charts.coefficients_chart(table)
        assert len(fig.data) == 1

    def test_subgroup_chart_with_real_data(self) -> None:
        table = pd.DataFrame(
            {
                "attribute": ["sex", "sex"],
                "group": ["male", "female"],
                "n": [100, 200],
                "sample_classification": ["adequate", "adequate"],
                "roc_auc": [0.7, 0.75],
            }
        )
        fig = charts.subgroup_chart(table, metric="roc_auc")
        assert len(fig.data) == 1

    def test_partial_dependence_chart_with_real_data(self) -> None:
        table = pd.DataFrame(
            {
                "feature": ["a", "a", "b"],
                "grid_value": [0, 1, 0],
                "average_prediction": [0.1, 0.2, 0.3],
            }
        )
        fig = charts.partial_dependence_chart(table, "a")
        assert len(fig.data) == 1
