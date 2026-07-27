"""Tests for credlens.modeling.tuning and calibration (Phase 8 sections
12, 14): tuning runs on train only, no nested-parallelism (n_jobs=1
throughout), calibration compares candidates on validation and can
legitimately keep the uncalibrated model."""

from __future__ import annotations

import pandas as pd
import pytest

from credlens.modeling.calibration import CalibrationResult, compare_calibration
from credlens.modeling.contracts import (
    EvaluationConfig,
    FeatureRegistry,
    TargetContract,
    load_evaluation_config,
    load_feature_registry,
    load_target_contract,
)
from credlens.modeling.features import engineer_features
from credlens.modeling.leakage import LeakageError
from credlens.modeling.training import N_JOBS, fit_model
from credlens.modeling.tuning import (
    TuningResult,
    tune_hist_gradient_boosting,
    tune_logistic_regression,
)


@pytest.fixture
def registry() -> FeatureRegistry:
    return load_feature_registry()


@pytest.fixture
def contract() -> TargetContract:
    return load_target_contract()


@pytest.fixture
def config() -> EvaluationConfig:
    return load_evaluation_config()


@pytest.fixture
def train_val_split(
    tiny_uci_frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    features = engineer_features(tiny_uci_frame)
    target = tiny_uci_frame["Y"]
    cutoff = int(len(features) * 0.8)
    return (
        features.iloc[:cutoff],
        target.iloc[:cutoff],
        features.iloc[cutoff:],
        target.iloc[cutoff:],
    )


class TestTuneLogisticRegression:
    def test_returns_a_fitted_pipeline_and_cv_results(
        self,
        train_val_split: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series],
        config: EvaluationConfig,
        registry: FeatureRegistry,
        contract: TargetContract,
    ) -> None:
        x_train, y_train, _x_val, _y_val = train_val_split
        result = tune_logistic_regression(
            x_train, y_train, config, registry=registry, contract=contract
        )
        assert isinstance(result, TuningResult)
        assert result.model_kind == "logistic_regression"
        assert "C" in result.best_params
        assert len(result.cv_results) == len(config.tuning["logistic_regression"]["C"])
        assert result.fitted.n_jobs == N_JOBS

    def test_rejects_a_leaky_training_frame(
        self,
        train_val_split: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series],
        config: EvaluationConfig,
        registry: FeatureRegistry,
        contract: TargetContract,
    ) -> None:
        x_train, y_train, _x_val, _y_val = train_val_split
        with pytest.raises(LeakageError):
            tune_logistic_regression(
                x_train.assign(Y=y_train), y_train, config, registry=registry, contract=contract
            )


class TestTuneHistGradientBoosting:
    def test_returns_a_fitted_pipeline(
        self,
        train_val_split: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series],
        config: EvaluationConfig,
        registry: FeatureRegistry,
        contract: TargetContract,
    ) -> None:
        x_train, y_train, _x_val, _y_val = train_val_split
        result = tune_hist_gradient_boosting(
            x_train, y_train, config, registry=registry, contract=contract
        )
        assert result.model_kind == "hist_gradient_boosting"
        assert "max_leaf_nodes" in result.best_params
        assert "learning_rate" in result.best_params


class TestCompareCalibration:
    def test_always_includes_the_uncalibrated_candidate(
        self,
        train_val_split: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series],
        config: EvaluationConfig,
        registry: FeatureRegistry,
        contract: TargetContract,
    ) -> None:
        x_train, y_train, x_val, y_val = train_val_split
        fitted = fit_model(
            "logistic_regression", x_train, y_train, registry=registry, contract=contract, seed=1
        )
        result = compare_calibration(fitted, x_train, y_train, x_val, y_val, config)
        assert isinstance(result, CalibrationResult)
        methods = {c.method for c in result.candidates}
        assert "none" in methods
        assert result.selected_method in methods

    def test_selected_pipeline_is_retrievable(
        self,
        train_val_split: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series],
        config: EvaluationConfig,
        registry: FeatureRegistry,
        contract: TargetContract,
    ) -> None:
        x_train, y_train, x_val, y_val = train_val_split
        fitted = fit_model(
            "logistic_regression", x_train, y_train, registry=registry, contract=contract, seed=1
        )
        result = compare_calibration(fitted, x_train, y_train, x_val, y_val, config)
        proba = result.selected_pipeline.predict_proba(x_val)[:, 1]
        assert ((proba >= 0) & (proba <= 1)).all()

    def test_isotonic_skipped_when_too_few_positives(
        self,
        train_val_split: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series],
        registry: FeatureRegistry,
        contract: TargetContract,
    ) -> None:
        from dataclasses import replace as dc_replace

        x_train, y_train, x_val, y_val = train_val_split
        small_config = load_evaluation_config()
        cal_cfg = dict(small_config.raw["calibration"])
        cal_cfg["isotonic_minimum_positive_count"] = 10_000_000
        small_config = dc_replace(small_config, raw={**small_config.raw, "calibration": cal_cfg})
        fitted = fit_model(
            "logistic_regression", x_train, y_train, registry=registry, contract=contract, seed=1
        )
        result = compare_calibration(fitted, x_train, y_train, x_val, y_val, small_config)
        assert "isotonic" not in {c.method for c in result.candidates}
