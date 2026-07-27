"""Tests for credlens.modeling.registry (Phase 8 sections 17, 24, 25,
26): experiment JSON round-trips, gates never use AUC alone, a failed
gate produces "No model eligible for registration", tampered artifacts
are rejected, batch scoring never includes a decision or sensitive data."""

from __future__ import annotations

from pathlib import Path

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
from credlens.modeling.registry import (
    Experiment,
    RegistryError,
    dependency_versions,
    evaluate_gates,
    list_experiments,
    load_experiment,
    load_model_candidate,
    load_model_candidate_manifest,
    register_model_candidate,
    score_batch,
    validate_model_candidate,
    write_experiment,
)
from credlens.modeling.training import fit_model


@pytest.fixture
def registry() -> FeatureRegistry:
    return load_feature_registry()


@pytest.fixture
def contract() -> TargetContract:
    return load_target_contract()


@pytest.fixture
def config() -> EvaluationConfig:
    return load_evaluation_config()


def _dummy_experiment(experiment_id: str = "EXP_test") -> Experiment:
    return Experiment(
        experiment_id=experiment_id,
        dataset_id="uci-default-credit",
        dataset_hash="abc123",
        split_hash="def456",
        target_column="Y",
        feature_set=["max_delinquency_status"],
        feature_registry_version="1.0.0",
        preprocessing="median imputation",
        estimator="logistic_regression",
        hyperparameters={"C": 1.0},
        seed=42,
        cv_description="StratifiedKFold(5)",
        metrics={},
        calibration={"selected_method": "none"},
        threshold_policy="illustrative",
        subgroup_audit_summary={},
        robustness_summary={},
        artifact_hash=None,
        dependency_versions=dependency_versions(),
        status="trained",
    )


class TestExperimentRegistry:
    def test_write_and_load_round_trips(self, tmp_path: Path) -> None:
        experiment = _dummy_experiment()
        write_experiment(experiment, tmp_path)
        loaded = load_experiment(tmp_path / "EXP_test.json")
        assert loaded.experiment_id == experiment.experiment_id
        assert loaded.hyperparameters == experiment.hyperparameters

    def test_list_experiments_returns_sorted_ids(self, tmp_path: Path) -> None:
        write_experiment(_dummy_experiment("EXP_b"), tmp_path)
        write_experiment(_dummy_experiment("EXP_a"), tmp_path)
        assert list_experiments(tmp_path) == ["EXP_a", "EXP_b"]

    def test_list_experiments_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        assert list_experiments(tmp_path / "nope") == []

    def test_load_missing_experiment_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RegistryError, match="not found"):
            load_experiment(tmp_path / "missing.json")


class TestEvaluateGates:
    def test_all_gates_pass_when_everything_is_good(self, config: EvaluationConfig) -> None:
        report = evaluate_gates(
            dummy_pr_auc=0.20,
            simple_rule_pr_auc=0.35,
            candidate_pr_auc=0.50,
            candidate_roc_auc=0.75,
            no_leakage_detected=True,
            calibration_acceptable=True,
            split_stability_roc_auc_stdev=0.01,
            subgroup_audit_completed=True,
            artifact_validated=True,
            config=config,
        )
        assert report.eligible is True
        assert "All gates passed" in report.reason

    def test_never_relies_only_on_auc(self, config: EvaluationConfig) -> None:
        # High AUC but leakage detected must still fail overall.
        report = evaluate_gates(
            dummy_pr_auc=0.20,
            simple_rule_pr_auc=0.35,
            candidate_pr_auc=0.90,
            candidate_roc_auc=0.99,
            no_leakage_detected=False,
            calibration_acceptable=True,
            split_stability_roc_auc_stdev=0.01,
            subgroup_audit_completed=True,
            artifact_validated=True,
            config=config,
        )
        assert report.eligible is False
        assert "No model eligible for registration" in report.reason

    def test_unstable_across_seeds_fails_the_stability_gate(self, config: EvaluationConfig) -> None:
        report = evaluate_gates(
            dummy_pr_auc=0.20,
            simple_rule_pr_auc=0.35,
            candidate_pr_auc=0.50,
            candidate_roc_auc=0.75,
            no_leakage_detected=True,
            calibration_acceptable=True,
            split_stability_roc_auc_stdev=0.5,
            subgroup_audit_completed=True,
            artifact_validated=True,
            config=config,
        )
        assert report.eligible is False
        gate = next(g for g in report.gates if g.name == "stable_across_split_seeds")
        assert gate.passed is False


class TestModelCandidateRegistry:
    def test_register_load_and_validate_round_trip(
        self,
        tiny_uci_frame: pd.DataFrame,
        registry: FeatureRegistry,
        contract: TargetContract,
        tmp_path: Path,
    ) -> None:
        features = engineer_features(tiny_uci_frame)
        target = tiny_uci_frame["Y"]
        fitted = fit_model(
            "logistic_regression", features, target, registry=registry, contract=contract, seed=1
        )
        manifest = register_model_candidate(
            fitted,
            model_id="MODEL_test",
            experiment_id="EXP_test",
            output_dir=tmp_path,
            feature_registry_version=registry.registry_version,
            test_metrics={"discrimination": {"roc_auc": 0.7}},
            limitations=["test only"],
            risk_band_cuts=[0.1, 0.2, 0.3],
        )
        assert manifest.status == "candidate"

        pipeline, loaded_manifest = load_model_candidate("MODEL_test", tmp_path)
        assert loaded_manifest.model_id == "MODEL_test"
        assert validate_model_candidate("MODEL_test", tmp_path) is True

        reloaded_manifest = load_model_candidate_manifest("MODEL_test", tmp_path)
        assert next(iter(reloaded_manifest.input_schema.keys())) == "max_delinquency_status"
        _ = pipeline

    def test_status_is_never_production_or_champion(
        self,
        tiny_uci_frame: pd.DataFrame,
        registry: FeatureRegistry,
        contract: TargetContract,
        tmp_path: Path,
    ) -> None:
        features = engineer_features(tiny_uci_frame)
        target = tiny_uci_frame["Y"]
        fitted = fit_model(
            "logistic_regression", features, target, registry=registry, contract=contract, seed=1
        )
        manifest = register_model_candidate(
            fitted,
            model_id="MODEL_test2",
            experiment_id="EXP_test",
            output_dir=tmp_path,
            feature_registry_version=registry.registry_version,
            test_metrics={},
            limitations=[],
            risk_band_cuts=[0.1, 0.2, 0.3],
        )
        assert manifest.status not in ("production", "champion")

    def test_tampered_artifact_is_rejected(
        self,
        tiny_uci_frame: pd.DataFrame,
        registry: FeatureRegistry,
        contract: TargetContract,
        tmp_path: Path,
    ) -> None:
        features = engineer_features(tiny_uci_frame)
        target = tiny_uci_frame["Y"]
        fitted = fit_model(
            "logistic_regression", features, target, registry=registry, contract=contract, seed=1
        )
        register_model_candidate(
            fitted,
            model_id="MODEL_tamper",
            experiment_id="EXP_test",
            output_dir=tmp_path,
            feature_registry_version=registry.registry_version,
            test_metrics={},
            limitations=[],
            risk_band_cuts=[0.1, 0.2, 0.3],
        )
        artifact_path = tmp_path / "MODEL_tamper.joblib"
        artifact_path.write_bytes(b"tampered bytes")
        with pytest.raises(RegistryError, match="hash mismatch"):
            load_model_candidate("MODEL_tamper", tmp_path)

    def test_missing_manifest_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RegistryError, match="No model candidate manifest"):
            load_model_candidate_manifest("does-not-exist", tmp_path)

    def test_missing_artifact_file_raises(
        self,
        tiny_uci_frame: pd.DataFrame,
        registry: FeatureRegistry,
        contract: TargetContract,
        tmp_path: Path,
    ) -> None:
        features = engineer_features(tiny_uci_frame)
        target = tiny_uci_frame["Y"]
        fitted = fit_model(
            "logistic_regression", features, target, registry=registry, contract=contract, seed=1
        )
        register_model_candidate(
            fitted,
            model_id="MODEL_missing_file",
            experiment_id="EXP_test",
            output_dir=tmp_path,
            feature_registry_version=registry.registry_version,
            test_metrics={},
            limitations=[],
            risk_band_cuts=[0.1, 0.2, 0.3],
        )
        (tmp_path / "MODEL_missing_file.joblib").unlink()
        with pytest.raises(RegistryError, match="not found"):
            load_model_candidate("MODEL_missing_file", tmp_path)


class TestScoreBatch:
    def test_never_includes_a_decision_or_sensitive_column(
        self,
        tiny_uci_frame: pd.DataFrame,
        registry: FeatureRegistry,
        contract: TargetContract,
        tmp_path: Path,
    ) -> None:
        features = engineer_features(tiny_uci_frame)
        target = tiny_uci_frame["Y"]
        fitted = fit_model(
            "logistic_regression", features, target, registry=registry, contract=contract, seed=1
        )
        manifest = register_model_candidate(
            fitted,
            model_id="MODEL_score",
            experiment_id="EXP_test",
            output_dir=tmp_path,
            feature_registry_version=registry.registry_version,
            test_metrics={},
            limitations=[],
            risk_band_cuts=[0.1, 0.2, 0.3],
        )
        pipeline, manifest = load_model_candidate("MODEL_score", tmp_path)
        input_df = features.copy()
        input_df["pseudonymous_record_id"] = [f"CASE-{i}" for i in range(len(input_df))]
        scored = score_batch(pipeline, manifest, input_df)
        forbidden = {"approve", "reject", "decision", "X2", "X3", "X4", "X5", "limit", "price"}
        assert forbidden.isdisjoint(scored.columns)
        assert scored["predicted_default_probability"].between(0, 1).all()
        assert set(scored["risk_band"]) <= {"low", "medium", "high", "very_high"}

    def test_missing_pseudonymous_id_column_raises(
        self,
        tiny_uci_frame: pd.DataFrame,
        registry: FeatureRegistry,
        contract: TargetContract,
        tmp_path: Path,
    ) -> None:
        features = engineer_features(tiny_uci_frame)
        target = tiny_uci_frame["Y"]
        fitted = fit_model(
            "logistic_regression", features, target, registry=registry, contract=contract, seed=1
        )
        manifest = register_model_candidate(
            fitted,
            model_id="MODEL_score2",
            experiment_id="EXP_test",
            output_dir=tmp_path,
            feature_registry_version=registry.registry_version,
            test_metrics={},
            limitations=[],
            risk_band_cuts=[0.1, 0.2, 0.3],
        )
        pipeline, manifest = load_model_candidate("MODEL_score2", tmp_path)
        with pytest.raises(RegistryError, match="pseudonymous_record_id"):
            score_batch(pipeline, manifest, features)

    def test_missing_feature_column_raises(
        self,
        tiny_uci_frame: pd.DataFrame,
        registry: FeatureRegistry,
        contract: TargetContract,
        tmp_path: Path,
    ) -> None:
        features = engineer_features(tiny_uci_frame)
        target = tiny_uci_frame["Y"]
        fitted = fit_model(
            "logistic_regression", features, target, registry=registry, contract=contract, seed=1
        )
        manifest = register_model_candidate(
            fitted,
            model_id="MODEL_score3",
            experiment_id="EXP_test",
            output_dir=tmp_path,
            feature_registry_version=registry.registry_version,
            test_metrics={},
            limitations=[],
            risk_band_cuts=[0.1, 0.2, 0.3],
        )
        pipeline, manifest = load_model_candidate("MODEL_score3", tmp_path)
        incomplete = features.drop(columns=["max_delinquency_status"])
        incomplete["pseudonymous_record_id"] = "x"
        with pytest.raises(RegistryError, match="missing required feature"):
            score_batch(pipeline, manifest, incomplete)
