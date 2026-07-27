"""Tests for credlens.modeling.leakage (Phase 8 sections 8, 21): static
allowlist rejection of target/ID/sensitive columns, and the negative-
control fixture helpers used by test_modeling_reporting.py's functional
controls."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from credlens.modeling.contracts import (
    FeatureRegistry,
    TargetContract,
    load_feature_registry,
    load_target_contract,
)
from credlens.modeling.features import FEATURE_COLUMNS
from credlens.modeling.leakage import (
    LeakageError,
    allowed_feature_names,
    assert_identifier_absent,
    assert_only_allowed_features,
    assert_restricted_absent,
    assert_target_absent,
    assert_training_frame_is_clean,
    id_only_frame,
    make_direct_target_feature,
    make_near_perfect_leakage_feature,
    restricted_column_names,
    shuffle_target,
)


@pytest.fixture
def registry() -> FeatureRegistry:
    return load_feature_registry()


@pytest.fixture
def contract() -> TargetContract:
    return load_target_contract()


class TestStaticAllowlist:
    def test_engineered_features_are_all_allowed(self, registry: FeatureRegistry) -> None:
        allowed = allowed_feature_names(registry)
        assert set(FEATURE_COLUMNS) <= allowed

    def test_restricted_columns_are_the_sensitive_group(self, registry: FeatureRegistry) -> None:
        assert restricted_column_names(registry) == frozenset({"X2", "X3", "X4", "X5"})

    def test_assert_only_allowed_features_passes_for_clean_frame(
        self, registry: FeatureRegistry
    ) -> None:
        assert_only_allowed_features(list(FEATURE_COLUMNS), registry)

    def test_assert_only_allowed_features_rejects_unknown_column(
        self, registry: FeatureRegistry
    ) -> None:
        with pytest.raises(LeakageError, match="not on the feature registry"):
            assert_only_allowed_features([*FEATURE_COLUMNS, "made_up_column"], registry)

    def test_assert_target_absent_passes_when_absent(self, contract: TargetContract) -> None:
        assert_target_absent(list(FEATURE_COLUMNS), contract)

    def test_assert_target_absent_rejects_target(self, contract: TargetContract) -> None:
        with pytest.raises(LeakageError, match="must never appear"):
            assert_target_absent([*FEATURE_COLUMNS, "Y"], contract)

    def test_assert_identifier_absent_rejects_id(self, contract: TargetContract) -> None:
        with pytest.raises(LeakageError, match="must never appear"):
            assert_identifier_absent([*FEATURE_COLUMNS, "ID"], contract)

    def test_assert_restricted_absent_rejects_sensitive_columns(
        self, registry: FeatureRegistry
    ) -> None:
        with pytest.raises(LeakageError, match="Restricted"):
            assert_restricted_absent([*FEATURE_COLUMNS, "X2"], registry)

    def test_assert_training_frame_is_clean_runs_every_check(
        self, registry: FeatureRegistry, contract: TargetContract
    ) -> None:
        assert_training_frame_is_clean(list(FEATURE_COLUMNS), registry, contract)
        with pytest.raises(LeakageError):
            assert_training_frame_is_clean([*FEATURE_COLUMNS, "X5"], registry, contract)
        with pytest.raises(LeakageError):
            assert_training_frame_is_clean([*FEATURE_COLUMNS, "Y"], registry, contract)
        with pytest.raises(LeakageError):
            assert_training_frame_is_clean([*FEATURE_COLUMNS, "ID"], registry, contract)


class TestNegativeControlFixtures:
    def test_shuffle_target_is_a_permutation(self) -> None:
        y = pd.Series([0, 0, 0, 1, 1, 1], name="Y")
        shuffled = shuffle_target(y, seed=1)
        assert sorted(shuffled.tolist()) == sorted(y.tolist())
        assert shuffled.name == "Y"

    def test_shuffle_target_is_deterministic_per_seed(self) -> None:
        y = pd.Series(range(20), name="Y")
        first = shuffle_target(y, seed=7)
        second = shuffle_target(y, seed=7)
        pd.testing.assert_series_equal(first, second)

    def test_make_direct_target_feature_is_the_target_renamed(self) -> None:
        y = pd.Series([0, 1, 0], name="Y")
        leak = make_direct_target_feature(y)
        assert leak.name == "target_direct_copy"
        assert leak.tolist() == y.tolist()

    def test_make_near_perfect_leakage_feature_is_close_to_target(self) -> None:
        y = pd.Series([0, 1, 0, 1, 0, 1] * 20, dtype=float, name="Y")
        leaky = make_near_perfect_leakage_feature(y, seed=1, noise_std=0.001)
        correlation = np.corrcoef(y, leaky)[0, 1]
        assert correlation > 0.99

    def test_id_only_frame_has_a_single_numeric_column(self) -> None:
        ids = pd.Series([1, 2, 3], name="ID")
        frame = id_only_frame(ids)
        assert list(frame.columns) == ["id_as_feature"]
        assert frame["id_as_feature"].tolist() == [1.0, 2.0, 3.0]
