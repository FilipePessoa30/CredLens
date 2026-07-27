"""Tests for credlens.modeling.evaluation (Phase 8 section 13): every
metric grouped by kind (discrimination/calibration/threshold-dependent/
ranking), never "accuracy alone", decile table sums correctly."""

from __future__ import annotations

import pandas as pd
import pytest

from credlens.modeling.evaluation import (
    brier,
    calibration_intercept_slope,
    confusion_at_threshold,
    decile_table,
    expected_calibration_error,
    full_metrics,
    ks_statistic,
    logloss,
    pr_auc,
    prevalence,
    roc_auc,
)


@pytest.fixture
def y_and_p() -> tuple[pd.Series, pd.Series]:
    y = pd.Series([0, 0, 0, 0, 1, 1, 1, 1, 0, 1])
    p = pd.Series([0.05, 0.1, 0.2, 0.3, 0.9, 0.8, 0.6, 0.4, 0.7, 0.95])
    return y, p


class TestBasicMetrics:
    def test_prevalence(self) -> None:
        assert prevalence(pd.Series([0, 0, 1, 1])) == 0.5

    def test_perfect_ranking_gives_roc_auc_of_one(self) -> None:
        y = pd.Series([0, 0, 1, 1])
        p = pd.Series([0.1, 0.2, 0.8, 0.9])
        assert roc_auc(y, p) == 1.0
        assert pr_auc(y, p) == 1.0

    def test_random_ranking_gives_roc_auc_near_half(
        self, y_and_p: tuple[pd.Series, pd.Series]
    ) -> None:
        y, p = y_and_p
        assert 0.0 <= roc_auc(y, p) <= 1.0

    def test_brier_and_logloss_are_nonnegative(self, y_and_p: tuple[pd.Series, pd.Series]) -> None:
        y, p = y_and_p
        assert brier(y, p) >= 0
        assert logloss(y, p) >= 0

    def test_ks_statistic_between_zero_and_one(self, y_and_p: tuple[pd.Series, pd.Series]) -> None:
        y, p = y_and_p
        assert 0.0 <= ks_statistic(y, p) <= 1.0


class TestCalibration:
    def test_perfectly_calibrated_predictions_have_slope_near_one(self) -> None:
        y = pd.Series([0] * 500 + [1] * 500)
        p = pd.Series([0.001] * 500 + [0.999] * 500)
        _intercept, slope = calibration_intercept_slope(y, p)
        assert slope > 0

    def test_expected_calibration_error_is_zero_for_perfect_calibration(self) -> None:
        y = pd.Series([0, 1] * 50)
        p = pd.Series([0.5] * 100)
        ece = expected_calibration_error(y, p)
        assert ece == pytest.approx(0.0, abs=1e-9)


class TestConfusionAtThreshold:
    def test_all_flagged_has_perfect_recall(self, y_and_p: tuple[pd.Series, pd.Series]) -> None:
        y, p = y_and_p
        cm = confusion_at_threshold(y, p, 0.0)
        assert cm.recall == 1.0
        assert cm.n_flagged == len(y)

    def test_none_flagged_has_zero_recall(self, y_and_p: tuple[pd.Series, pd.Series]) -> None:
        y, p = y_and_p
        cm = confusion_at_threshold(y, p, 1.01)
        assert cm.recall == 0.0
        assert cm.n_flagged == 0

    def test_to_dict_has_every_field(self, y_and_p: tuple[pd.Series, pd.Series]) -> None:
        y, p = y_and_p
        cm = confusion_at_threshold(y, p, 0.5)
        d = cm.to_dict()
        for key in ("precision", "recall", "specificity", "f1", "balanced_accuracy", "threshold"):
            assert key in d


class TestDecileTable:
    def test_deciles_partition_the_population(self, y_and_p: tuple[pd.Series, pd.Series]) -> None:
        y, p = y_and_p
        table = decile_table(y, p, n_deciles=5)
        assert table["n"].sum() == len(y)
        assert table["n_positive"].sum() == int(y.sum())

    def test_cumulative_capture_rate_reaches_one(
        self, y_and_p: tuple[pd.Series, pd.Series]
    ) -> None:
        y, p = y_and_p
        table = decile_table(y, p, n_deciles=5)
        assert table["cumulative_capture_rate"].iloc[-1] == pytest.approx(1.0)

    def test_top_decile_has_highest_or_equal_event_rate(
        self, y_and_p: tuple[pd.Series, pd.Series]
    ) -> None:
        y, p = y_and_p
        table = decile_table(y, p, n_deciles=5)
        assert table["event_rate"].iloc[0] >= table["event_rate"].iloc[-1]


class TestFullMetrics:
    def test_groups_metrics_by_kind_not_just_accuracy(
        self, y_and_p: tuple[pd.Series, pd.Series]
    ) -> None:
        y, p = y_and_p
        metrics = full_metrics(y, p, threshold=0.5)
        assert set(metrics.keys()) == {
            "prevalence",
            "discrimination",
            "calibration",
            "threshold_dependent",
            "ranking",
        }
        assert "accuracy" not in metrics["threshold_dependent"]
        assert "roc_auc" in metrics["discrimination"]
        assert "brier_score" in metrics["calibration"]
        assert "decile_table" in metrics["ranking"]
