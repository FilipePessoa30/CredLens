"""Tests for credlens.modeling.contracts (Phase 8 section 5): target
binary, no nulls, documented domain, prevalence within tolerance, no
duplicate IDs, target absent from features."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from credlens.modeling.contracts import (
    ContractError,
    TargetContract,
    assert_target_not_in_features,
    load_evaluation_config,
    load_feature_registry,
    load_target_contract,
    validate_target_contract,
)
from credlens.modeling.data import load_uci_default_credit


@pytest.fixture
def real_contract() -> TargetContract:
    return load_target_contract()


@pytest.fixture
def real_df() -> pd.DataFrame:
    return load_uci_default_credit()


class TestLoadContracts:
    def test_target_contract_fields(self, real_contract: TargetContract) -> None:
        assert real_contract.target_column == "Y"
        assert real_contract.identifier_column == "ID"
        assert real_contract.positive_label == 1
        assert real_contract.negative_label == 0
        assert real_contract.source_id == "uci-default-credit"
        assert "Behavioral" in real_contract.name_en
        assert len(real_contract.excluded_columns) == 5

    def test_feature_registry_fields(self) -> None:
        registry = load_feature_registry()
        assert registry.registry_version == "1.0.0"
        assert len(registry.allowed_feature_names) == 18
        assert set(registry.audit_only_columns) == {"X2", "X3", "X4", "X5"}

    def test_evaluation_config_sections(self) -> None:
        config = load_evaluation_config()
        assert config.split["train_fraction"] == 0.6
        assert config.tuning["cv_folds"] == 5
        assert config.calibration["cv_folds"] == 5
        assert config.thresholds["illustrative_operating_points"]
        assert config.uncertainty["bootstrap"]["n_resamples"] == 1000
        assert config.robustness["seed"]
        assert config.negative_controls["shuffled_target_seed"]
        assert config.subgroup_audit["age_buckets"]
        assert config.gates["min_test_roc_auc"] == 0.60

    def test_missing_contract_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ContractError):
            load_target_contract(tmp_path)

    def test_missing_registry_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ContractError):
            load_feature_registry(tmp_path)

    def test_missing_evaluation_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ContractError):
            load_evaluation_config(tmp_path)


class TestValidateTargetContract:
    def test_real_data_passes(self, real_df: pd.DataFrame, real_contract: TargetContract) -> None:
        validate_target_contract(real_df, real_contract, manifest_hash=None)

    def test_matching_manifest_hash_passes(
        self, real_df: pd.DataFrame, real_contract: TargetContract
    ) -> None:
        validate_target_contract(
            real_df, real_contract, manifest_hash=real_contract.acquired_hash_sha256
        )

    def test_mismatched_manifest_hash_raises(
        self, real_df: pd.DataFrame, real_contract: TargetContract
    ) -> None:
        with pytest.raises(ContractError, match="no longer matches"):
            validate_target_contract(real_df, real_contract, manifest_hash="deadbeef")

    def test_missing_target_column_raises(
        self, real_df: pd.DataFrame, real_contract: TargetContract
    ) -> None:
        with pytest.raises(ContractError, match="not found"):
            validate_target_contract(real_df.drop(columns=["Y"]), real_contract)

    def test_null_target_raises(self, real_df: pd.DataFrame, real_contract: TargetContract) -> None:
        broken = real_df.copy()
        broken.loc[0, "Y"] = None
        with pytest.raises(ContractError, match="null"):
            validate_target_contract(broken, real_contract)

    def test_out_of_domain_target_label_raises(
        self, real_df: pd.DataFrame, real_contract: TargetContract
    ) -> None:
        broken = real_df.copy()
        broken.loc[0, "Y"] = 2
        with pytest.raises(ContractError, match="labels outside"):
            validate_target_contract(broken, real_contract)

    def test_prevalence_drift_raises(
        self, real_df: pd.DataFrame, real_contract: TargetContract
    ) -> None:
        broken = real_df.copy()
        broken["Y"] = 1
        with pytest.raises(ContractError, match="prevalence"):
            validate_target_contract(broken, real_contract)

    def test_duplicate_identifier_raises(
        self, real_df: pd.DataFrame, real_contract: TargetContract
    ) -> None:
        broken = real_df.copy()
        broken.loc[1, "ID"] = broken.loc[0, "ID"]
        with pytest.raises(ContractError, match="duplicate"):
            validate_target_contract(broken, real_contract)

    def test_stability_across_two_loads(self, real_contract: TargetContract) -> None:
        first = load_uci_default_credit()
        second = load_uci_default_credit()
        validate_target_contract(first, real_contract)
        validate_target_contract(second, real_contract)
        assert first["Y"].mean() == second["Y"].mean()


class TestAssertTargetNotInFeatures:
    def test_passes_when_absent(self, real_contract: TargetContract) -> None:
        assert_target_not_in_features(["max_delinquency_status"], real_contract)

    def test_raises_when_present(self, real_contract: TargetContract) -> None:
        with pytest.raises(ContractError):
            assert_target_not_in_features(["max_delinquency_status", "Y"], real_contract)
