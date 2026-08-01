"""Tests for credlens.modeling.reason_code_policy and its enforcement in
credlens.modeling.interpretability (Phase 10 gate E).

Fast tests exercise the policy loader/filter with no I/O beyond reading
the real project's `config/model_validation/reason_codes.yml`. The
enforcement-integration tests reuse the already-trained OFFICIAL
`EXP_behavioral_default_v1` logistic pipeline (read-only) to confirm no
`prohibited` feature can ever be surfaced, real coefficients included.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import pytest

from credlens.modeling.features import FEATURE_COLUMNS
from credlens.modeling.reason_code_policy import (
    ReasonCodePolicyError,
    filter_and_rank_for_reason_codes,
    load_reason_code_policy,
)
from credlens.modeling.training import FittedModel

_PROHIBITED = {
    "avg_bill_amount",
    "total_bill_amount",
    "bill_trend",
    "bill_variability",
    "worst_payment_to_bill_ratio",
    "limit_exposure_distance",
}
_CONDITIONAL = {
    "months_delinquent_count",
    "consecutive_months_delinquent",
    "avg_payment_amount",
    "total_payment_amount",
    "payment_variation",
}
_ALLOWED = set(FEATURE_COLUMNS) - _PROHIBITED - _CONDITIONAL


class TestLoadReasonCodePolicy:
    def test_loads_the_real_project_policy(self) -> None:
        policy = load_reason_code_policy()
        assert policy.governed_model_id == "MODEL_behavioral_default_v1"
        assert policy.version == "1.0.0"

    def test_every_feature_is_classified_exactly_once(self) -> None:
        policy = load_reason_code_policy()
        all_governed = (
            set(policy.allowed_features)
            | set(policy.conditional_features)
            | set(policy.prohibited_features)
        )
        assert all_governed == set(FEATURE_COLUMNS)
        # No feature appears in more than one tier.
        assert len(policy.allowed_features) + len(policy.conditional_features) + len(
            policy.prohibited_features
        ) == len(FEATURE_COLUMNS)

    def test_matches_the_documented_tier_split(self) -> None:
        policy = load_reason_code_policy()
        assert set(policy.allowed_features) == _ALLOWED
        assert set(policy.conditional_features) == _CONDITIONAL
        assert set(policy.prohibited_features) == _PROHIBITED

    def test_raises_when_missing(self, tmp_path: Path) -> None:
        with pytest.raises(ReasonCodePolicyError):
            load_reason_code_policy(tmp_path)

    def test_conditional_caveats_are_present_and_bilingual(self) -> None:
        policy = load_reason_code_policy()
        for feature in _CONDITIONAL:
            assert policy.caveat(feature, "en")
            assert policy.caveat(feature, "pt-BR")

    def test_allowed_features_have_no_caveat(self) -> None:
        policy = load_reason_code_policy()
        for feature in _ALLOWED:
            assert policy.caveat(feature, "en") is None

    def test_allowed_and_conditional_features_have_approved_descriptions(self) -> None:
        policy = load_reason_code_policy()
        for feature in _ALLOWED | _CONDITIONAL:
            assert policy.description(feature, "en")
            assert policy.description(feature, "pt-BR")


class TestFilterAndRankForReasonCodes:
    def test_prohibited_features_never_survive(self) -> None:
        policy = load_reason_code_policy()
        # Deliberately put the LARGEST contribution on a prohibited
        # feature - it must never appear, no matter how large.
        contributions = [
            ("bill_variability", 10.0),
            ("max_delinquency_status", 0.5),
            ("payment_coverage_rate", 0.3),
        ]
        result = filter_and_rank_for_reason_codes(contributions, policy, top_k=3)
        features = [row[0] for row in result]
        assert "bill_variability" not in features
        assert features == ["max_delinquency_status", "payment_coverage_rate"]

    def test_ranking_preserved_among_eligible_features(self) -> None:
        policy = load_reason_code_policy()
        contributions = [
            ("payment_coverage_rate", 0.1),
            ("max_delinquency_status", 0.9),
            ("months_without_payment", 0.5),
        ]
        result = filter_and_rank_for_reason_codes(contributions, policy, top_k=2)
        assert [row[0] for row in result] == ["max_delinquency_status", "months_without_payment"]

    def test_conditional_features_carry_their_tier(self) -> None:
        policy = load_reason_code_policy()
        contributions = [("months_delinquent_count", 1.0)]
        result = filter_and_rank_for_reason_codes(contributions, policy, top_k=1)
        assert result == [("months_delinquent_count", 1.0, "conditional")]

    def test_ungoverned_feature_is_excluded(self) -> None:
        policy = load_reason_code_policy()
        contributions = [("not_a_real_feature", 99.0), ("max_delinquency_status", 0.1)]
        result = filter_and_rank_for_reason_codes(contributions, policy, top_k=2)
        assert [row[0] for row in result] == ["max_delinquency_status"]


@pytest.mark.slow
class TestEnforcementOnTheRealOfficialModel:
    """Reuses the already-trained, already-registered official logistic
    pipeline (read-only - never refit, never touches split/predictions)
    to confirm the enforcement wired into
    credlens.modeling.interpretability never surfaces a prohibited
    feature on real coefficients."""

    def test_local_explanation_never_surfaces_a_prohibited_feature(self) -> None:
        from credlens.modeling.data import load_uci_default_credit
        from credlens.modeling.features import engineer_features
        from credlens.modeling.interpretability import local_explanation

        pipeline = joblib.load(
            "reports/modeling/experiments/EXP_behavioral_default_v1/models/logistic_regression.joblib"
        )
        fitted = FittedModel(
            model_kind="logistic_regression",
            pipeline=pipeline,
            hyperparameters={},
            seed=42,
            n_jobs=1,
            fit_seconds=0.0,
            feature_columns=list(FEATURE_COLUMNS),
        )
        df = load_uci_default_credit().head(200)
        features = engineer_features(df)
        for positional_idx in range(len(features)):
            explanation = local_explanation(
                fitted,
                features.iloc[[positional_idx]],
                raw_id=positional_idx,
                predicted_probability=0.5,
                actual_label=None,
                case_label="probe",
            )
            surfaced = {r.feature for r in explanation.reason_codes}
            assert surfaced.isdisjoint(_PROHIBITED)
            for reason_code in explanation.reason_codes:
                if reason_code.feature in _CONDITIONAL:
                    assert reason_code.tier == "conditional"
                    assert reason_code.caveat_en is not None
                elif reason_code.feature in _ALLOWED:
                    assert reason_code.tier == "allowed"
                    assert reason_code.caveat_en is None

    def test_official_local_explanations_file_has_no_prohibited_feature(self) -> None:
        import json

        data = json.loads(
            Path(
                "reports/modeling/tables/EXP_behavioral_default_v1__local_explanations.json"
            ).read_text(encoding="utf-8")
        )
        for case in data:
            surfaced = {r["feature"] for r in case["reason_codes"]}
            assert surfaced.isdisjoint(_PROHIBITED)
            for reason_code in case["reason_codes"]:
                assert reason_code["tier"] in ("allowed", "conditional")

    def test_isolated_repo_without_policy_falls_back_gracefully(self, tmp_path: Path) -> None:
        """No config/model_validation/ present at all (mirrors Phase 8's
        own isolated_repo_root fixture) - must not raise, must fall back
        to the unfiltered top-K ranking."""
        from credlens.modeling.data import load_uci_default_credit
        from credlens.modeling.features import engineer_features
        from credlens.modeling.interpretability import local_explanation

        pipeline = joblib.load(
            "reports/modeling/experiments/EXP_behavioral_default_v1/models/logistic_regression.joblib"
        )
        fitted = FittedModel(
            model_kind="logistic_regression",
            pipeline=pipeline,
            hyperparameters={},
            seed=42,
            n_jobs=1,
            fit_seconds=0.0,
            feature_columns=list(FEATURE_COLUMNS),
        )
        df = load_uci_default_credit().head(1)
        features = engineer_features(df)
        explanation = local_explanation(
            fitted,
            features.iloc[[0]],
            raw_id=1,
            predicted_probability=0.5,
            actual_label=None,
            case_label="probe",
            repo_root=tmp_path,
        )
        assert len(explanation.reason_codes) == 3
        for reason_code in explanation.reason_codes:
            assert reason_code.tier == "ungoverned"
            assert reason_code.caveat_en is None
