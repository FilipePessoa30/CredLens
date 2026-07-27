"""Tests for credlens.modeling.thresholds and uncertainty (Phase 8
sections 15, 16): thresholds are defined on validation and only
evaluated on test; bootstrap/split-stability register seed, method,
percentiles, and effective sample size."""

from __future__ import annotations

import pandas as pd
import pytest

from credlens.modeling.contracts import (
    EvaluationConfig,
    FeatureRegistry,
    TargetContract,
    load_evaluation_config,
    load_feature_registry,
    load_target_contract,
)
from credlens.modeling.features import engineer_features
from credlens.modeling.thresholds import (
    ILLUSTRATIVE_LABEL_EN,
    operating_points_from_config,
    threshold_for_population_share,
    threshold_for_recall,
)
from credlens.modeling.training import fit_model, predict_proba_positive
from credlens.modeling.uncertainty import bootstrap_test_metrics, split_stability_sweep


@pytest.fixture
def config() -> EvaluationConfig:
    return load_evaluation_config()


@pytest.fixture
def registry() -> FeatureRegistry:
    return load_feature_registry()


@pytest.fixture
def contract() -> TargetContract:
    return load_target_contract()


@pytest.fixture
def val_test_predictions(
    tiny_uci_frame: pd.DataFrame, registry: FeatureRegistry, contract: TargetContract
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    features = engineer_features(tiny_uci_frame)
    target = tiny_uci_frame["Y"]
    cutoff_train = int(len(features) * 0.6)
    cutoff_val = int(len(features) * 0.8)
    x_train, y_train = features.iloc[:cutoff_train], target.iloc[:cutoff_train]
    x_val, y_val = features.iloc[cutoff_train:cutoff_val], target.iloc[cutoff_train:cutoff_val]
    x_test, y_test = features.iloc[cutoff_val:], target.iloc[cutoff_val:]
    fitted = fit_model(
        "logistic_regression", x_train, y_train, registry=registry, contract=contract, seed=1
    )
    p_val = predict_proba_positive(fitted, x_val)
    p_test = predict_proba_positive(fitted, x_test)
    return y_val, p_val, y_test, p_test


class TestThresholdHelpers:
    def test_population_share_threshold_flags_the_right_fraction(self) -> None:
        p_val = pd.Series(range(100)) / 100.0
        threshold = threshold_for_population_share(p_val, 0.1)
        flagged = (p_val >= threshold).sum()
        assert flagged == pytest.approx(10, abs=1)

    def test_recall_threshold_is_within_the_score_range(self) -> None:
        y_val = pd.Series([0, 0, 0, 1, 1, 1, 1, 0, 1, 0])
        p_val = pd.Series([0.1, 0.2, 0.3, 0.9, 0.8, 0.6, 0.4, 0.7, 0.95, 0.05])
        threshold = threshold_for_recall(y_val, p_val, 0.5)
        assert p_val.min() <= threshold <= p_val.max()


class TestOperatingPointsFromConfig:
    def test_every_configured_point_is_illustrative(
        self,
        val_test_predictions: tuple[pd.Series, pd.Series, pd.Series, pd.Series],
        config: EvaluationConfig,
    ) -> None:
        y_val, p_val, y_test, p_test = val_test_predictions
        points = operating_points_from_config(y_val, p_val, y_test, p_test, config)
        assert len(points) == len(config.thresholds["illustrative_operating_points"])
        for point in points:
            d = point.to_dict()
            assert d["label_en"] == ILLUSTRATIVE_LABEL_EN
            assert d["n_total"] == len(y_test)

    def test_unknown_operating_point_type_raises(
        self, val_test_predictions: tuple[pd.Series, pd.Series, pd.Series, pd.Series]
    ) -> None:
        from dataclasses import replace as dc_replace

        y_val, p_val, y_test, p_test = val_test_predictions
        config = load_evaluation_config()
        broken_thresholds = dict(config.raw["thresholds"])
        broken_thresholds["illustrative_operating_points"] = [
            {"name": "bogus", "type": "not_a_type", "value": 0.1}
        ]
        broken_config = dc_replace(config, raw={**config.raw, "thresholds": broken_thresholds})
        with pytest.raises(ValueError, match="Unknown operating point type"):
            operating_points_from_config(y_val, p_val, y_test, p_test, broken_config)


class TestBootstrapTestMetrics:
    def test_registers_seed_method_and_percentiles(
        self,
        val_test_predictions: tuple[pd.Series, pd.Series, pd.Series, pd.Series],
        config: EvaluationConfig,
    ) -> None:
        _y_val, _p_val, y_test, p_test = val_test_predictions
        threshold = float(p_test.median())
        report = bootstrap_test_metrics(
            y_test, p_test, top_decile_threshold=threshold, config=config
        )
        assert report.effective_n_test == len(y_test)
        assert report.n_resamples == config.uncertainty["bootstrap"]["n_resamples"]
        for metric_result in report.metrics.values():
            assert metric_result.p2_5 <= metric_result.p50 <= metric_result.p97_5


class TestSplitStabilitySweep:
    def test_runs_one_fresh_split_per_seed(
        self,
        tiny_uci_frame: pd.DataFrame,
        registry: FeatureRegistry,
        contract: TargetContract,
        config: EvaluationConfig,
    ) -> None:
        report = split_stability_sweep(
            tiny_uci_frame, registry=registry, contract=contract, config=config
        )
        assert len(report.runs) == len(config.uncertainty["split_stability"]["seeds"])
        assert report.roc_auc_stdev >= 0.0
