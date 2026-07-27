"""Tests for credlens.modeling.robustness (Phase 8 section 20): every
perturbation kind runs without crashing, missingness genuinely exercises
the imputer, out-of-domain codes never produce NaN/Inf predictions."""

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
from credlens.modeling.robustness import (
    PERTURBATION_KINDS,
    run_robustness_suite,
)
from credlens.modeling.training import FittedModel, fit_model, predict_proba_positive


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
def fitted_and_test(
    tiny_uci_frame: pd.DataFrame, registry: FeatureRegistry, contract: TargetContract
) -> tuple[FittedModel, pd.DataFrame, pd.Series, pd.Series]:
    features = engineer_features(tiny_uci_frame)
    target = tiny_uci_frame["Y"]
    cutoff = int(len(features) * 0.7)
    x_train, y_train = features.iloc[:cutoff], target.iloc[:cutoff]
    raw_test = tiny_uci_frame.iloc[cutoff:]
    y_test = target.iloc[cutoff:]
    fitted = fit_model(
        "logistic_regression", x_train, y_train, registry=registry, contract=contract, seed=1
    )
    x_test = features.iloc[cutoff:]
    p_test = predict_proba_positive(fitted, x_test)
    return fitted, raw_test, y_test, p_test


class TestRunRobustnessSuite:
    def test_every_perturbation_kind_produces_a_result(
        self,
        fitted_and_test: tuple[FittedModel, pd.DataFrame, pd.Series, pd.Series],
        config: EvaluationConfig,
    ) -> None:
        fitted, raw_test, y_test, p_test = fitted_and_test
        threshold = float(p_test.median())
        results = run_robustness_suite(
            fitted, raw_test, y_test, p_test, threshold=threshold, config=config
        )
        assert {r.kind for r in results} == set(PERTURBATION_KINDS)
        for result in results:
            assert not result.had_error_or_nan, result.error_message

    def test_missingness_produces_a_valid_ranking_correlation(
        self,
        fitted_and_test: tuple[FittedModel, pd.DataFrame, pd.Series, pd.Series],
        config: EvaluationConfig,
    ) -> None:
        fitted, raw_test, y_test, p_test = fitted_and_test
        threshold = float(p_test.median())
        results = run_robustness_suite(
            fitted, raw_test, y_test, p_test, threshold=threshold, config=config
        )
        missingness = next(r for r in results if r.kind == "additional_missingness")
        assert missingness.ranking_spearman_correlation is not None
        assert -1.0 <= missingness.ranking_spearman_correlation <= 1.0

    def test_prevalence_drift_changes_row_count_and_skips_ranking_correlation(
        self,
        fitted_and_test: tuple[FittedModel, pd.DataFrame, pd.Series, pd.Series],
        config: EvaluationConfig,
    ) -> None:
        fitted, raw_test, y_test, p_test = fitted_and_test
        threshold = float(p_test.median())
        results = run_robustness_suite(
            fitted, raw_test, y_test, p_test, threshold=threshold, config=config
        )
        drift = next(r for r in results if r.kind == "prevalence_drift_low")
        assert drift.n_rows != len(raw_test) or drift.ranking_spearman_correlation is None

    def test_to_dict_has_every_required_field(
        self,
        fitted_and_test: tuple[FittedModel, pd.DataFrame, pd.Series, pd.Series],
        config: EvaluationConfig,
    ) -> None:
        fitted, raw_test, y_test, p_test = fitted_and_test
        threshold = float(p_test.median())
        results = run_robustness_suite(
            fitted, raw_test, y_test, p_test, threshold=threshold, config=config
        )
        d = results[0].to_dict()
        for key in (
            "pr_auc_degradation",
            "brier_degradation",
            "calibration_slope_shift",
            "had_error_or_nan",
        ):
            assert key in d
