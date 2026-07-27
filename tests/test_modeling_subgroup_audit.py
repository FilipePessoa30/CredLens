"""Tests for credlens.modeling.subgroup_audit (Phase 8 section 19): one
fixed threshold for every group, insufficient-sample groups excluded
from gap calculations, sensitive attributes joined ONLY here."""

from __future__ import annotations

import pandas as pd
import pytest

from credlens.modeling.contracts import (
    FeatureRegistry,
    TargetContract,
    load_feature_registry,
    load_target_contract,
)
from credlens.modeling.features import engineer_features
from credlens.modeling.subgroup_audit import FAIRNESS_SECTION_LABEL_EN, run_subgroup_audit
from credlens.modeling.training import fit_model, predict_proba_positive

_AGE_BUCKETS = [[18, 30], [30, 40], [40, 50], [50, 100]]


@pytest.fixture
def registry() -> FeatureRegistry:
    return load_feature_registry()


@pytest.fixture
def contract() -> TargetContract:
    return load_target_contract()


@pytest.fixture
def scored_frame(
    tiny_uci_frame: pd.DataFrame, registry: FeatureRegistry, contract: TargetContract
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    features = engineer_features(tiny_uci_frame)
    target = tiny_uci_frame["Y"]
    fitted = fit_model(
        "logistic_regression", features, target, registry=registry, contract=contract, seed=1
    )
    p = predict_proba_positive(fitted, features)
    return tiny_uci_frame, target, p


class TestRunSubgroupAudit:
    def test_covers_all_four_attributes(
        self, scored_frame: tuple[pd.DataFrame, pd.Series, pd.Series]
    ) -> None:
        raw_df, y, p = scored_frame
        report = run_subgroup_audit(raw_df, y, p, threshold=0.5, age_buckets=_AGE_BUCKETS)
        attributes = {m.attribute for m in report.metrics}
        assert attributes == {"sex", "education", "marriage", "age_bucket"}

    def test_every_group_uses_the_same_fixed_threshold(
        self, scored_frame: tuple[pd.DataFrame, pd.Series, pd.Series]
    ) -> None:
        raw_df, y, p = scored_frame
        report = run_subgroup_audit(raw_df, y, p, threshold=0.5, age_buckets=_AGE_BUCKETS)
        assert report.threshold == 0.5

    def test_small_groups_are_classified_insufficient(self) -> None:
        raw_df = pd.DataFrame(
            {"X2": [1] * 5 + [2] * 100, "X3": [1] * 105, "X4": [1] * 105, "X5": [30] * 105}
        )
        y = pd.Series([0, 1, 0, 1, 0] + [0, 1] * 50, index=raw_df.index)
        p = pd.Series([0.5] * 105, index=raw_df.index)
        report = run_subgroup_audit(raw_df, y, p, threshold=0.5, age_buckets=_AGE_BUCKETS)
        sex_1 = next(m for m in report.metrics if m.attribute == "sex" and m.group == "male")
        assert sex_1.sample_classification == "insufficient"
        assert "sex=male" in report.excluded_insufficient_groups

    def test_insufficient_groups_never_drive_the_max_gap(self) -> None:
        raw_df = pd.DataFrame(
            {"X2": [1] * 5 + [2] * 100, "X3": [1] * 105, "X4": [1] * 105, "X5": [30] * 105}
        )
        y = pd.Series([1] * 5 + [0, 1] * 50, index=raw_df.index)
        p = pd.Series([0.9] * 5 + [0.1] * 100, index=raw_df.index)
        report = run_subgroup_audit(raw_df, y, p, threshold=0.5, age_buckets=_AGE_BUCKETS)
        # Only one non-insufficient "sex" group remains, so no gap is
        # computable from sex alone - this must not crash.
        assert report.to_dict()["label_en"] == FAIRNESS_SECTION_LABEL_EN

    def test_to_dict_includes_required_caveats(
        self, scored_frame: tuple[pd.DataFrame, pd.Series, pd.Series]
    ) -> None:
        raw_df, y, p = scored_frame
        report = run_subgroup_audit(raw_df, y, p, threshold=0.5, age_buckets=_AGE_BUCKETS)
        d = report.to_dict()
        assert "caveats_en" in d
        assert any("compliance" in c for c in d["caveats_en"])
