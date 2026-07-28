"""Tests for credlens.model_validation.collinearity/coefficient_audit
(Phase 9 section 7) - fast, using `tiny_uci_frame` (no real 30k-row
benchmark needed for these pure-function unit tests).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from credlens.model_validation import coefficient_audit, collinearity
from credlens.modeling.features import engineer_features


@pytest.fixture
def features(tiny_uci_frame: pd.DataFrame) -> pd.DataFrame:
    return engineer_features(tiny_uci_frame)


@pytest.fixture
def target(tiny_uci_frame: pd.DataFrame) -> pd.Series:
    return tiny_uci_frame["Y"]


class TestCorrelationAndVif:
    def test_correlation_matrix_is_square_and_symmetric(self, features: pd.DataFrame) -> None:
        corr = collinearity.compute_correlation_matrix(features)
        assert corr.shape[0] == corr.shape[1]
        assert np.allclose(corr.to_numpy(), corr.to_numpy().T, atol=1e-9, equal_nan=True)

    def test_perfectly_collinear_features_have_infinite_vif(self) -> None:
        rng = np.random.default_rng(0)
        base = rng.normal(size=300)
        frame = pd.DataFrame({"a": base, "b": base * 2.0, "c": rng.normal(size=300)})
        vif = collinearity.compute_vif(frame)
        by_feature = {row.feature: row.vif for row in vif}
        assert not np.isfinite(by_feature["a"])
        assert not np.isfinite(by_feature["b"])

    def test_independent_features_have_low_vif(self) -> None:
        rng = np.random.default_rng(1)
        frame = pd.DataFrame({"a": rng.normal(size=1000), "b": rng.normal(size=1000)})
        vif = collinearity.compute_vif(frame)
        assert all(row.vif < 2.0 for row in vif)

    def test_condition_number_is_higher_for_collinear_data(self) -> None:
        rng = np.random.default_rng(2)
        base = rng.normal(size=500)
        collinear = pd.DataFrame({"a": base, "b": base + rng.normal(scale=0.01, size=500)})
        independent = pd.DataFrame({"a": rng.normal(size=500), "b": rng.normal(size=500)})
        assert collinearity.condition_number(collinear) > collinearity.condition_number(independent)

    def test_high_correlation_pairs_detects_known_pair(self) -> None:
        rng = np.random.default_rng(3)
        base = rng.normal(size=200)
        frame = pd.DataFrame({"a": base, "b": base, "c": rng.normal(size=200)})
        corr = collinearity.compute_correlation_matrix(frame)
        pairs = collinearity.high_correlation_pairs(corr, threshold=0.9)
        assert ("a", "b") in [(p.feature_a, p.feature_b) for p in pairs]

    def test_run_collinearity_audit_real_features(self, features: pd.DataFrame) -> None:
        cfg = {
            "vif_flag_threshold": 5.0,
            "vif_action_threshold": 10.0,
            "high_correlation_threshold": 0.7,
            "condition_number_flag_threshold": 15.0,
            "condition_number_action_threshold": 30.0,
        }
        report = collinearity.run_collinearity_audit(features, cfg)
        assert len(report.vif_table) == len(features.columns)
        assert report.condition_number_value > 0

    def test_iteratively_reduce_by_vif_drops_the_worst_offender(self) -> None:
        rng = np.random.default_rng(4)
        base = rng.normal(size=1000)
        frame = pd.DataFrame(
            {
                "redundant_a": base,
                "redundant_b": base + rng.normal(scale=1e-6, size=1000),
                "independent_c": rng.normal(size=1000),
                "independent_d": rng.normal(size=1000),
                "independent_e": rng.normal(size=1000),
            }
        )
        kept, steps = collinearity.iteratively_reduce_by_vif(frame, threshold=10.0, min_features=3)
        assert len(kept) < len(frame.columns)
        assert len(steps) >= 1

    def test_iteratively_reduce_respects_min_features(self) -> None:
        rng = np.random.default_rng(5)
        base = rng.normal(size=500)
        frame = pd.DataFrame({f"f{i}": base + rng.normal(scale=1e-6, size=500) for i in range(6)})
        kept, _ = collinearity.iteratively_reduce_by_vif(frame, threshold=1.5, min_features=4)
        assert len(kept) >= 4


class TestCoefficientAudit:
    def test_bootstrap_samples_have_expected_shape(
        self, features: pd.DataFrame, target: pd.Series
    ) -> None:
        samples = coefficient_audit.bootstrap_coefficient_samples(
            features, target, n_resamples=5, seed=42
        )
        assert samples.shape == (5, len(features.columns))

    def test_cv_fold_samples_have_expected_shape(
        self, features: pd.DataFrame, target: pd.Series
    ) -> None:
        samples = coefficient_audit.cv_fold_coefficient_samples(
            features, target, n_folds=3, seed=42
        )
        assert samples.shape[0] == 3

    def test_regularization_sensitivity_samples_shape(
        self, features: pd.DataFrame, target: pd.Series
    ) -> None:
        samples = coefficient_audit.regularization_sensitivity_samples(
            features, target, c_grid=[0.01, 1.0, 10.0]
        )
        assert samples.shape[0] == 3

    def test_classify_coefficients_flags_a_perfectly_redundant_pair(self) -> None:
        rng = np.random.default_rng(6)
        n = 2000
        base = rng.normal(size=n)
        x = pd.DataFrame({"a": base, "b": base * 2.0, "c": rng.normal(size=n)})
        logit = 0.5 * base - 0.3
        y = pd.Series((rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int))

        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        pipeline = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
        pipeline.fit(x, y)
        original = dict(
            zip(x.columns, pipeline.named_steps["logisticregression"].coef_[0], strict=True)
        )

        bootstrap_samples = coefficient_audit.bootstrap_coefficient_samples(
            x, y, n_resamples=20, seed=1
        )
        cv_samples = coefficient_audit.cv_fold_coefficient_samples(x, y, n_folds=3, seed=1)
        reg_samples = coefficient_audit.regularization_sensitivity_samples(
            x, y, c_grid=[0.01, 0.1, 1.0, 10.0]
        )
        cfg = {
            "vif_action_threshold": 10.0,
            "sign_flip_rate_unstable_threshold": 0.05,
            "low_magnitude_odds_ratio_band": [0.95, 1.05],
        }
        collinearity_report = collinearity.run_collinearity_audit(
            x,
            {
                "vif_flag_threshold": 5.0,
                "vif_action_threshold": 10.0,
                "high_correlation_threshold": 0.7,
                "condition_number_flag_threshold": 15.0,
                "condition_number_action_threshold": 30.0,
            },
        )
        classifications = coefficient_audit.classify_coefficients(
            original, bootstrap_samples, cv_samples, reg_samples, collinearity_report, cfg
        )
        by_feature = {c.feature: c.category for c in classifications}
        assert by_feature["a"] == "redundant"
        assert by_feature["b"] == "redundant"

    def test_unstable_language_never_claims_protective_effect(self) -> None:
        assert "protective" not in coefficient_audit.UNSTABLE_LANGUAGE_EN.lower() or (
            "not evidence" in coefficient_audit.UNSTABLE_LANGUAGE_EN.lower()
        )
