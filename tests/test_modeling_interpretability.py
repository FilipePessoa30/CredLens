"""Tests for credlens.modeling.interpretability (Phase 8 section 18):
coefficients/odds ratios, permutation importance, partial dependence,
pseudonymized local explanations that never touch a sensitive attribute,
and representative-case selection."""

from __future__ import annotations

import pandas as pd
import pytest

from credlens.modeling.contracts import (
    FeatureRegistry,
    TargetContract,
    load_feature_registry,
    load_target_contract,
)
from credlens.modeling.features import FEATURE_COLUMNS, engineer_features
from credlens.modeling.interpretability import (
    compute_partial_dependence,
    compute_permutation_importance,
    local_explanation,
    logistic_coefficients,
    pseudonymize_id,
    select_representative_cases,
)
from credlens.modeling.training import FittedModel, fit_model, predict_proba_positive


@pytest.fixture
def registry() -> FeatureRegistry:
    return load_feature_registry()


@pytest.fixture
def contract() -> TargetContract:
    return load_target_contract()


@pytest.fixture
def fitted_logistic(
    tiny_uci_frame: pd.DataFrame, registry: FeatureRegistry, contract: TargetContract
) -> tuple[FittedModel, pd.DataFrame, pd.Series]:
    features = engineer_features(tiny_uci_frame)
    target = tiny_uci_frame["Y"]
    fitted = fit_model(
        "logistic_regression", features, target, registry=registry, contract=contract, seed=1
    )
    return fitted, features, target


class TestPseudonymizeId:
    def test_deterministic_for_the_same_id(self) -> None:
        assert pseudonymize_id(42) == pseudonymize_id(42)

    def test_never_leaks_the_raw_id(self) -> None:
        pseudo = pseudonymize_id(12345)
        assert "12345" not in pseudo
        assert pseudo.startswith("CASE-")


class TestLogisticCoefficients:
    def test_covers_every_feature_sorted_by_magnitude(
        self, fitted_logistic: tuple[FittedModel, pd.DataFrame, pd.Series]
    ) -> None:
        fitted, _features, _target = fitted_logistic
        rows = logistic_coefficients(fitted)
        assert {r.feature for r in rows} == set(FEATURE_COLUMNS)
        magnitudes = [abs(r.coefficient) for r in rows]
        assert magnitudes == sorted(magnitudes, reverse=True)

    def test_odds_ratio_matches_exp_of_coefficient(
        self, fitted_logistic: tuple[FittedModel, pd.DataFrame, pd.Series]
    ) -> None:
        import math

        fitted, _features, _target = fitted_logistic
        rows = logistic_coefficients(fitted)
        for row in rows:
            assert row.odds_ratio == pytest.approx(math.exp(row.coefficient))

    def test_rejects_non_logistic_model(
        self, tiny_uci_frame: pd.DataFrame, registry: FeatureRegistry, contract: TargetContract
    ) -> None:
        features = engineer_features(tiny_uci_frame)
        target = tiny_uci_frame["Y"]
        hgb = fit_model(
            "hist_gradient_boosting", features, target, registry=registry, contract=contract, seed=1
        )
        with pytest.raises(ValueError, match="logistic_regression"):
            logistic_coefficients(hgb)


class TestPermutationImportanceAndPdp:
    def test_permutation_importance_covers_every_feature(
        self, fitted_logistic: tuple[FittedModel, pd.DataFrame, pd.Series]
    ) -> None:
        fitted, features, target = fitted_logistic
        rows = compute_permutation_importance(fitted, features, target)
        assert {r.feature for r in rows} == set(features.columns)

    def test_partial_dependence_returns_a_curve_per_feature(
        self, fitted_logistic: tuple[FittedModel, pd.DataFrame, pd.Series]
    ) -> None:
        fitted, features, _target = fitted_logistic
        curves = compute_partial_dependence(fitted, features, list(FEATURE_COLUMNS), top_k=3)
        assert len(curves) == 3
        for curve in curves:
            assert len(curve.grid_values) == len(curve.average_prediction)


class TestLocalExplanationAndRepresentativeCases:
    def test_representative_cases_cover_expected_labels(
        self, fitted_logistic: tuple[FittedModel, pd.DataFrame, pd.Series]
    ) -> None:
        fitted, features, target = fitted_logistic
        p = predict_proba_positive(fitted, features)
        ids = pd.Series(range(len(features)), index=features.index)
        cases = select_representative_cases(target, p, ids, threshold=0.5)
        assert "high_risk" in cases
        assert "low_risk" in cases
        assert "intermediate_risk" in cases

    def test_local_explanation_never_references_a_sensitive_attribute(
        self, fitted_logistic: tuple[FittedModel, pd.DataFrame, pd.Series]
    ) -> None:
        fitted, features, _target = fitted_logistic
        row = features.iloc[[0]]
        explanation = local_explanation(
            fitted, row, raw_id=1, predicted_probability=0.5, actual_label=1, case_label="test"
        )
        reason_features = {r.feature for r in explanation.reason_codes}
        assert reason_features <= set(FEATURE_COLUMNS)
        assert reason_features.isdisjoint({"X2", "X3", "X4", "X5"})

    def test_local_explanation_pseudonymizes_the_id(
        self, fitted_logistic: tuple[FittedModel, pd.DataFrame, pd.Series]
    ) -> None:
        fitted, features, _target = fitted_logistic
        row = features.iloc[[0]]
        explanation = local_explanation(
            fitted, row, raw_id=999, predicted_probability=0.3, actual_label=0, case_label="tn"
        )
        assert explanation.pseudonymous_id == pseudonymize_id(999)
        assert explanation.to_dict()["pseudonymous_id"] == pseudonymize_id(999)
