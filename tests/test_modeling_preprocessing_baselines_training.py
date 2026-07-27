"""Tests for credlens.modeling.preprocessing, baselines, and training
(Phase 8 sections 11.1, 11.2, 11.3): every model kind fits through the
single leakage-checked entry point, imputation/scaling behave as
documented, and the transparent single-feature baseline is monotonic."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from credlens.modeling.baselines import (
    SimpleDelinquencyRule,
    build_dummy_prior,
    build_dummy_stratified,
)
from credlens.modeling.contracts import (
    FeatureRegistry,
    TargetContract,
    load_feature_registry,
    load_target_contract,
)
from credlens.modeling.features import engineer_features
from credlens.modeling.leakage import LeakageError
from credlens.modeling.preprocessing import build_preprocessing_pipeline
from credlens.modeling.training import (
    MODEL_KINDS,
    default_estimator,
    fit_model,
    predict_proba_positive,
)


@pytest.fixture
def registry() -> FeatureRegistry:
    return load_feature_registry()


@pytest.fixture
def contract() -> TargetContract:
    return load_target_contract()


@pytest.fixture
def features_and_target(tiny_uci_frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    features = engineer_features(tiny_uci_frame)
    return features, tiny_uci_frame["Y"]


class TestPreprocessingPipeline:
    def test_logistic_pipeline_imputes_and_scales(self) -> None:
        pipeline = build_preprocessing_pipeline("logistic_regression")
        assert [name for name, _ in pipeline.steps] == ["imputer", "scaler"]

    def test_hgb_pipeline_only_imputes(self) -> None:
        pipeline = build_preprocessing_pipeline("hist_gradient_boosting")
        assert [name for name, _ in pipeline.steps] == ["imputer"]

    def test_pipeline_output_preserves_column_names(
        self, features_and_target: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        features, _ = features_and_target
        pipeline = build_preprocessing_pipeline("logistic_regression")
        transformed = pipeline.fit_transform(features)
        assert list(transformed.columns) == list(features.columns)

    def test_pipeline_handles_missing_values(
        self, features_and_target: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        features, _ = features_and_target
        with_gaps = features.copy()
        with_gaps.iloc[0, 0] = np.nan
        pipeline = build_preprocessing_pipeline("hist_gradient_boosting")
        transformed = pipeline.fit_transform(with_gaps)
        assert np.isfinite(transformed.to_numpy(dtype=float)).all()


class TestBaselines:
    def test_dummy_prior_predicts_the_class_prior(
        self, features_and_target: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        features, target = features_and_target
        model = build_dummy_prior()
        model.fit(features, target)
        proba = model.predict_proba(features)[:, 1]
        assert np.allclose(proba, target.mean())

    def test_dummy_stratified_is_seeded(
        self, features_and_target: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        features, target = features_and_target
        first = build_dummy_stratified(seed=1)
        first.fit(features, target)
        second = build_dummy_stratified(seed=1)
        second.fit(features, target)
        assert np.array_equal(first.predict(features), second.predict(features))

    def test_simple_delinquency_rule_is_monotonic(
        self, features_and_target: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        features, target = features_and_target
        rule = SimpleDelinquencyRule()
        rule.fit(features, target)
        proba = rule.predict_proba(features)[:, 1]
        order = np.argsort(features["max_delinquency_status"].to_numpy())
        sorted_proba = proba[order]
        # Isotonic regression guarantees a non-decreasing fit.
        assert np.all(np.diff(sorted_proba) >= -1e-9)

    def test_simple_delinquency_rule_predict_before_fit_raises(self) -> None:
        rule = SimpleDelinquencyRule()
        with pytest.raises(RuntimeError):
            rule.predict_proba(pd.DataFrame({"max_delinquency_status": [0.0]}))

    def test_simple_delinquency_rule_accepts_ndarray(
        self, features_and_target: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        features, target = features_and_target
        rule = SimpleDelinquencyRule()
        rule.fit(features, target)
        proba = rule.predict_proba(features.to_numpy())
        assert proba.shape == (len(features), 2)

    def test_simple_delinquency_rule_get_set_params(self) -> None:
        rule = SimpleDelinquencyRule()
        assert rule.get_params() == {}
        assert rule.set_params() is rule


class TestFitModel:
    def test_fits_every_model_kind(
        self,
        features_and_target: tuple[pd.DataFrame, pd.Series],
        registry: FeatureRegistry,
        contract: TargetContract,
    ) -> None:
        features, target = features_and_target
        for kind in MODEL_KINDS:
            fitted = fit_model(kind, features, target, registry=registry, contract=contract, seed=1)
            assert fitted.model_kind == kind
            proba = predict_proba_positive(fitted, features)
            assert proba.between(0, 1).all()

    def test_rejects_a_frame_with_the_target_column(
        self,
        features_and_target: tuple[pd.DataFrame, pd.Series],
        registry: FeatureRegistry,
        contract: TargetContract,
    ) -> None:
        features, target = features_and_target
        leaky = features.assign(Y=target)
        with pytest.raises(LeakageError):
            fit_model("logistic_regression", leaky, target, registry=registry, contract=contract)

    def test_rejects_a_frame_with_a_sensitive_column(
        self,
        features_and_target: tuple[pd.DataFrame, pd.Series],
        registry: FeatureRegistry,
        contract: TargetContract,
    ) -> None:
        features, target = features_and_target
        leaky = features.assign(X2=1)
        with pytest.raises(LeakageError):
            fit_model("logistic_regression", leaky, target, registry=registry, contract=contract)

    def test_unknown_model_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown model_kind"):
            default_estimator("not_a_model", seed=1)  # type: ignore[arg-type]

    def test_predict_proba_positive_uses_feature_order(
        self,
        features_and_target: tuple[pd.DataFrame, pd.Series],
        registry: FeatureRegistry,
        contract: TargetContract,
    ) -> None:
        features, target = features_and_target
        fitted = fit_model(
            "logistic_regression", features, target, registry=registry, contract=contract, seed=1
        )
        proba = predict_proba_positive(fitted, features)
        assert proba.name == "predicted_default_probability"
        assert list(proba.index) == list(features.index)
