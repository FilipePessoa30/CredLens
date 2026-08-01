"""Orchestrates the staged Phase 8 pipeline
(`train -> evaluate -> compare -> explain -> audit-groups -> stress-test
-> register -> report`) behind the `credlens model ...` CLI subcommands.

Every stage PERSISTS what the next stage needs to disk (fitted
pipelines under `reports/modeling/experiments/<id>/models/*.joblib`,
predictions/tables under `reports/modeling/tables/`, the experiment
record under `reports/modeling/experiments/<id>.json`) so each CLI
invocation is a fresh, independent process - exactly like
`credlens analysis run`/`credlens warehouse build` before it. Numeric
claims in model cards/technical reports are always read back out of
these written tables, never typed by hand.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from credlens.modeling import data as modeling_data
from credlens.modeling.calibration import compare_calibration
from credlens.modeling.contracts import (
    EvaluationConfig,
    FeatureRegistry,
    TargetContract,
    load_evaluation_config,
    load_feature_registry,
    load_target_contract,
    validate_target_contract,
)
from credlens.modeling.evaluation import full_metrics
from credlens.modeling.features import FEATURE_COLUMNS, engineer_features
from credlens.modeling.interpretability import (
    compute_partial_dependence,
    compute_permutation_importance,
    local_explanation,
    logistic_coefficients,
    select_representative_cases,
)
from credlens.modeling.leakage import (
    assert_only_allowed_features,
    id_only_frame,
    make_direct_target_feature,
    make_near_perfect_leakage_feature,
    shuffle_target,
)
from credlens.modeling.registry import (
    Experiment,
    GateReport,
    ModelCandidateManifest,
    dependency_versions,
    evaluate_gates,
    load_experiment,
    register_model_candidate,
    write_experiment,
)
from credlens.modeling.robustness import run_robustness_suite
from credlens.modeling.splitting import (
    apply_split_assignment_table,
    create_split,
    load_split_assignment_table,
    write_split_assignment_table,
)
from credlens.modeling.subgroup_audit import run_subgroup_audit
from credlens.modeling.thresholds import operating_points_from_config
from credlens.modeling.training import FittedModel, ModelKind, fit_model, predict_proba_positive
from credlens.modeling.tuning import tune_hist_gradient_boosting, tune_logistic_regression
from credlens.modeling.uncertainty import bootstrap_test_metrics, split_stability_sweep

EXPERIMENTS_DIR = Path("reports/modeling/experiments")
TABLES_DIR = Path("reports/modeling/tables")
FIGURES_DIR = Path("reports/modeling/figures")

MAIN_CANDIDATE_KIND: ModelKind = "logistic_regression"
CHALLENGER_KIND: ModelKind = "hist_gradient_boosting"
ALL_MODEL_KINDS: tuple[ModelKind, ...] = (
    "dummy_prior",
    "simple_rule",
    "logistic_regression",
    "hist_gradient_boosting",
)


class ReportingError(Exception):
    """Raised for pipeline-stage ordering/IO failures."""


def data_audit_report(repo_root: Path | None = None) -> dict[str, Any]:
    """`credlens model data-audit` - reproduces
    `credlens.modeling.data.audit_source` as a CLI-facing dict, never
    re-downloading anything."""
    return modeling_data.audit_source(repo_root or Path.cwd()).to_dict()


def validate_features_report(repo_root: Path | None = None) -> dict[str, Any]:
    """`credlens model validate-features` - engineers features from the
    real acquired source and re-runs every static leakage control against
    the resulting frame, confirming it is training-clean before any model
    is ever fit."""
    from credlens.modeling.leakage import assert_training_frame_is_clean

    repo_root = repo_root or Path.cwd()
    registry = load_feature_registry(repo_root)
    contract = load_target_contract(repo_root)
    df = modeling_data.load_uci_default_credit(repo_root)
    features = engineer_features(df)
    assert_training_frame_is_clean(list(features.columns), registry, contract)
    return {
        "feature_registry_version": registry.registry_version,
        "feature_count": len(features.columns),
        "features": list(features.columns),
        "audit_only_columns": registry.audit_only_columns,
        "all_finite": bool(np.isfinite(features.to_numpy(dtype=float)).all()),
    }


def _exp_dir(experiment_id: str, repo_root: Path) -> Path:
    return repo_root / EXPERIMENTS_DIR / experiment_id


def _models_dir(experiment_id: str, repo_root: Path) -> Path:
    return _exp_dir(experiment_id, repo_root) / "models"


def _table_path(experiment_id: str, name: str, repo_root: Path) -> Path:
    return repo_root / TABLES_DIR / f"{experiment_id}__{name}.csv"


def _experiment_path(experiment_id: str, repo_root: Path) -> Path:
    return repo_root / EXPERIMENTS_DIR / f"{experiment_id}.json"


def _combined_split_hash(train_hash: str, val_hash: str, test_hash: str) -> str:
    return hashlib.sha256(f"{train_hash}|{val_hash}|{test_hash}".encode()).hexdigest()


def _load_top10_threshold(experiment_id: str, repo_root: Path) -> float:
    """The `top_10_pct` operating point's TEST-evaluated threshold, shared
    by explain/audit-groups/stress-test so every downstream diagnostic
    uses the exact same fixed threshold - falls back to 0.5 only if
    `evaluate` has not run yet."""
    thresholds_path = _table_path(experiment_id, "thresholds", repo_root)
    if not thresholds_path.is_file():
        return 0.5
    thresholds_table = pd.read_csv(thresholds_path)
    top10_row = thresholds_table[thresholds_table["name"] == "top_10_pct"]
    if top10_row.empty:
        return 0.5
    return float(top10_row.iloc[0]["threshold"])


def _wrap_fitted(pipeline: Any, model_kind: ModelKind, seed: int) -> FittedModel:
    return FittedModel(
        model_kind=model_kind,
        pipeline=pipeline,
        hyperparameters={},
        seed=seed,
        n_jobs=1,
        fit_seconds=0.0,
        feature_columns=list(FEATURE_COLUMNS),
    )


@dataclass(frozen=True)
class NegativeControlResult:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


def run_negative_controls(
    x_train: pd.DataFrame,
    y_train: pd.Series,
    x_val: pd.DataFrame,
    y_val: pd.Series,
    ids_train: pd.Series,
    ids_val: pd.Series,
    registry: FeatureRegistry,
    contract: TargetContract,
    config: EvaluationConfig,
) -> list[NegativeControlResult]:
    """Phase 8 sections 8.2/21 - every control here actually re-fits and
    measures, never just checks a column name."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    def _scaled_logistic() -> Any:
        return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))

    nc_cfg = config.negative_controls
    results = []

    try:
        assert_only_allowed_features(["Y"], registry)
        results.append(
            NegativeControlResult("reject_direct_target_column", False, "should have raised")
        )
    except Exception:
        results.append(
            NegativeControlResult(
                "reject_direct_target_column", True, "static allowlist rejected the raw target"
            )
        )

    leak_col = str(make_direct_target_feature(y_train).name)
    try:
        assert_only_allowed_features([*FEATURE_COLUMNS, leak_col], registry)
        results.append(
            NegativeControlResult("reject_target_copy_feature", False, "should have raised")
        )
    except Exception:
        results.append(
            NegativeControlResult(
                "reject_target_copy_feature",
                True,
                "static allowlist rejected a renamed target copy",
            )
        )

    near_perfect = make_near_perfect_leakage_feature(
        y_train, seed=int(nc_cfg["shuffled_target_seed"])
    )
    x_leak = x_train.assign(near_perfect_leak=near_perfect)
    model = _scaled_logistic()
    model.fit(x_leak, y_train)
    near_perfect_val = make_near_perfect_leakage_feature(
        y_val, seed=int(nc_cfg["shuffled_target_seed"])
    )
    x_leak_val = x_val.assign(near_perfect_leak=near_perfect_val)
    leak_auc = float(roc_auc_score(y_val, model.predict_proba(x_leak_val)[:, 1]))
    detected = leak_auc >= float(nc_cfg["min_expected_near_perfect_leakage_roc_auc"])
    results.append(
        NegativeControlResult(
            "near_perfect_leakage_is_detectable",
            detected,
            f"ROC-AUC with an injected near-perfect-leak column = {leak_auc:.4f} "
            f"(never added to the real allowlisted training frame)",
        )
    )

    max_deviation = float(nc_cfg["max_deviation_from_random_roc_auc"])

    shuffled_y_train = shuffle_target(y_train, seed=int(nc_cfg["shuffled_target_seed"]))
    shuffled_model = _scaled_logistic()
    shuffled_model.fit(x_train, shuffled_y_train)
    shuffled_auc = float(roc_auc_score(y_val, shuffled_model.predict_proba(x_val)[:, 1]))
    shuffled_ok = abs(shuffled_auc - 0.5) <= max_deviation
    results.append(
        NegativeControlResult(
            "shuffled_target_scores_near_random",
            shuffled_ok,
            f"ROC-AUC with a shuffled target = {shuffled_auc:.4f} "
            f"(within {max_deviation:.2f} of random, 0.5, required)",
        )
    )

    id_train_frame = id_only_frame(ids_train)
    id_val_frame = id_only_frame(ids_val)
    id_model = _scaled_logistic()
    id_model.fit(id_train_frame, y_train)
    id_auc = float(roc_auc_score(y_val, id_model.predict_proba(id_val_frame)[:, 1]))
    id_ok = abs(id_auc - 0.5) <= max_deviation
    results.append(
        NegativeControlResult(
            "id_only_model_carries_no_signal",
            id_ok,
            f"ROC-AUC using ONLY the record identifier as a feature = {id_auc:.4f}",
        )
    )

    return results


def create_official_split(
    experiment_id: str, *, repo_root: Path | None = None, seed: int = 42
) -> Any:
    """Standalone `credlens model create-split` step. Idempotent by
    design - if a split assignment already exists for this experiment_id
    it is left untouched (re-running `create-split` with a different
    seed on an EXISTING experiment_id is refused, since `train` would
    then silently train on a different partition than the one this
    command reports)."""
    repo_root = repo_root or Path.cwd()
    contract = load_target_contract(repo_root)
    config = load_evaluation_config(repo_root)
    df = modeling_data.load_uci_default_credit(repo_root)

    exp_dir = _exp_dir(experiment_id, repo_root)
    split_path = exp_dir / "split_assignment.csv"
    if split_path.is_file():
        raise ReportingError(
            f"A split already exists for experiment '{experiment_id}' at '{split_path}' - "
            "use a new --experiment-id to create a different split."
        )

    assignment = create_split(
        df,
        id_column=contract.identifier_column,
        target_column=contract.target_column,
        config=config,
        seed=seed,
    )
    write_split_assignment_table(
        df, assignment, id_column=contract.identifier_column, path=split_path
    )
    return assignment


def train_experiment(
    experiment_id: str, *, repo_root: Path | None = None, seed: int = 42
) -> Experiment:
    repo_root = repo_root or Path.cwd()
    contract = load_target_contract(repo_root)
    registry = load_feature_registry(repo_root)
    config = load_evaluation_config(repo_root)
    audit = modeling_data.audit_source(repo_root)
    df = modeling_data.load_uci_default_credit(repo_root)
    validate_target_contract(df, contract, manifest_hash=audit.sha256)

    exp_dir = _exp_dir(experiment_id, repo_root)
    split_path = exp_dir / "split_assignment.csv"
    if split_path.is_file():
        table = load_split_assignment_table(split_path)
        assignment = apply_split_assignment_table(df, table, id_column=contract.identifier_column)
    else:
        assignment = create_split(
            df,
            id_column=contract.identifier_column,
            target_column=contract.target_column,
            config=config,
            seed=seed,
        )
        write_split_assignment_table(
            df, assignment, id_column=contract.identifier_column, path=split_path
        )

    features = engineer_features(df)
    target = df[contract.target_column]
    x_train = features.loc[assignment.train_index]
    y_train = target.loc[assignment.train_index]
    x_val = features.loc[assignment.validation_index]
    y_val = target.loc[assignment.validation_index]
    ids_train = df.loc[assignment.train_index, contract.identifier_column]
    ids_val = df.loc[assignment.validation_index, contract.identifier_column]

    negative_controls = run_negative_controls(
        x_train, y_train, x_val, y_val, ids_train, ids_val, registry, contract, config
    )
    no_leakage_detected = all(r.passed for r in negative_controls)

    dummy = fit_model(
        "dummy_prior", x_train, y_train, registry=registry, contract=contract, seed=seed
    )
    simple_rule = fit_model(
        "simple_rule", x_train, y_train, registry=registry, contract=contract, seed=seed
    )
    tuned_logistic = tune_logistic_regression(
        x_train, y_train, config, registry=registry, contract=contract
    )
    tuned_hgb = tune_hist_gradient_boosting(
        x_train, y_train, config, registry=registry, contract=contract
    )

    calibration_result = compare_calibration(
        tuned_logistic.fitted, x_train, y_train, x_val, y_val, config
    )
    calibrated_logistic_pipeline = calibration_result.selected_pipeline

    models_dir = _models_dir(experiment_id, repo_root)
    models_dir.mkdir(parents=True, exist_ok=True)
    import joblib

    joblib.dump(dummy.pipeline, models_dir / "dummy_prior.joblib")
    joblib.dump(simple_rule.pipeline, models_dir / "simple_rule.joblib")
    joblib.dump(calibrated_logistic_pipeline, models_dir / "logistic_regression.joblib")
    joblib.dump(tuned_hgb.fitted.pipeline, models_dir / "hist_gradient_boosting.joblib")

    experiment = Experiment(
        experiment_id=experiment_id,
        dataset_id=modeling_data.SOURCE_ID,
        dataset_hash=audit.sha256,
        split_hash=_combined_split_hash(
            assignment.manifest.train_id_hash,
            assignment.manifest.validation_id_hash,
            assignment.manifest.test_id_hash,
        ),
        target_column=contract.target_column,
        feature_set=list(FEATURE_COLUMNS),
        feature_registry_version=registry.registry_version,
        preprocessing="median imputation (+ standardization for logistic regression)",
        estimator=f"{MAIN_CANDIDATE_KIND} (main) / {CHALLENGER_KIND} (challenger)",
        hyperparameters=tuned_logistic.best_params,
        seed=seed,
        cv_description=(
            f"StratifiedKFold(n_splits={tuned_logistic.cv_folds}), scoring=average_precision, "
            "train-only"
        ),
        metrics={},
        calibration=calibration_result.to_dict(),
        threshold_policy="Illustrative review-capacity scenario (never profit-optimized)",
        subgroup_audit_summary={},
        robustness_summary={},
        artifact_hash=None,
        dependency_versions=dependency_versions(),
        status="trained",
        warnings=[r.to_dict()["detail"] for r in negative_controls if not r.passed],
    )
    (repo_root / EXPERIMENTS_DIR).mkdir(parents=True, exist_ok=True)
    write_experiment(experiment, repo_root / EXPERIMENTS_DIR)

    controls_path = _table_path(experiment_id, "negative_controls", repo_root)
    controls_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([r.to_dict() for r in negative_controls]).to_csv(controls_path, index=False)

    tuning_path_lr = _table_path(experiment_id, "tuning_logistic_regression", repo_root)
    pd.DataFrame(tuned_logistic.cv_results).to_csv(tuning_path_lr, index=False)
    tuning_path_hgb = _table_path(experiment_id, "tuning_hist_gradient_boosting", repo_root)
    pd.DataFrame(tuned_hgb.cv_results).to_csv(tuning_path_hgb, index=False)

    _ = no_leakage_detected  # surfaced via the negative_controls table + experiment warnings
    return experiment


def _reload_models(experiment_id: str, repo_root: Path, seed: int) -> dict[ModelKind, FittedModel]:
    import joblib

    models_dir = _models_dir(experiment_id, repo_root)
    fitted: dict[ModelKind, FittedModel] = {}
    for kind in ALL_MODEL_KINDS:
        path = models_dir / f"{kind}.joblib"
        if not path.is_file():
            raise ReportingError(f"No trained model artifact for '{kind}' at '{path}'.")
        fitted[kind] = _wrap_fitted(joblib.load(path), kind, seed)
    return fitted


def _load_experiment_data(
    experiment_id: str, repo_root: Path
) -> tuple[pd.DataFrame, TargetContract, FeatureRegistry, EvaluationConfig, Any]:
    contract = load_target_contract(repo_root)
    registry = load_feature_registry(repo_root)
    config = load_evaluation_config(repo_root)
    df = modeling_data.load_uci_default_credit(repo_root)
    table = load_split_assignment_table(_exp_dir(experiment_id, repo_root) / "split_assignment.csv")
    assignment = apply_split_assignment_table(df, table, id_column=contract.identifier_column)
    return df, contract, registry, config, assignment


def evaluate_experiment(experiment_id: str, *, repo_root: Path | None = None) -> Experiment:
    repo_root = repo_root or Path.cwd()
    experiment = load_experiment(_experiment_path(experiment_id, repo_root))
    df, contract, _registry, config, assignment = _load_experiment_data(experiment_id, repo_root)
    fitted = _reload_models(experiment_id, repo_root, experiment.seed)

    features = engineer_features(df)
    target = df[contract.target_column]
    x_val = features.loc[assignment.validation_index]
    y_val = target.loc[assignment.validation_index]
    x_test = features.loc[assignment.test_index]
    y_test = target.loc[assignment.test_index]
    ids_val = df.loc[assignment.validation_index, contract.identifier_column]
    ids_test = df.loc[assignment.test_index, contract.identifier_column]

    predictions_val = pd.DataFrame({"id": ids_val.to_numpy(), "y_true": y_val.to_numpy()})
    predictions_test = pd.DataFrame({"id": ids_test.to_numpy(), "y_true": y_test.to_numpy()})
    metrics_val: dict[str, Any] = {}
    metrics_test: dict[str, Any] = {}
    for kind, model in fitted.items():
        p_val = predict_proba_positive(model, x_val)
        p_test = predict_proba_positive(model, x_test)
        predictions_val[kind] = p_val.to_numpy()
        predictions_test[kind] = p_test.to_numpy()
        metrics_val[kind] = full_metrics(y_val, p_val)
        metrics_test[kind] = full_metrics(y_test, p_test)

    predictions_val.to_csv(_table_path(experiment_id, "predictions_val", repo_root), index=False)
    predictions_test.to_csv(_table_path(experiment_id, "predictions_test", repo_root), index=False)

    p_val_main = predictions_val[MAIN_CANDIDATE_KIND]
    p_test_main = predictions_test[MAIN_CANDIDATE_KIND]
    ops = operating_points_from_config(y_val, p_val_main, y_test, p_test_main, config)
    pd.DataFrame([o.to_dict() for o in ops]).to_csv(
        _table_path(experiment_id, "thresholds", repo_root), index=False
    )
    top10 = next(o for o in ops if o.name == "top_10_pct").threshold

    bootstrap = bootstrap_test_metrics(
        y_test, p_test_main, top_decile_threshold=top10, config=config
    )
    (repo_root / TABLES_DIR / f"{experiment_id}__bootstrap.json").write_text(
        json.dumps(bootstrap.to_dict(), indent=2), encoding="utf-8"
    )

    stability = split_stability_sweep(
        df,
        registry=load_feature_registry(repo_root),
        contract=contract,
        config=config,
        model_kind=MAIN_CANDIDATE_KIND,
    )
    pd.DataFrame(stability.to_dict()["runs"]).to_csv(
        _table_path(experiment_id, "split_stability", repo_root), index=False
    )

    updated = Experiment(
        **{
            **experiment.to_dict(),
            "metrics": {
                "validation": metrics_val,
                "test": metrics_test,
                "bootstrap": bootstrap.to_dict(),
                "split_stability": stability.to_dict(),
                "operating_points": [o.to_dict() for o in ops],
            },
            "status": "evaluated",
        }
    )
    write_experiment(updated, repo_root / EXPERIMENTS_DIR)
    return updated


def compare_models(experiment_id: str, *, repo_root: Path | None = None) -> pd.DataFrame:
    repo_root = repo_root or Path.cwd()
    experiment = load_experiment(_experiment_path(experiment_id, repo_root))
    test_metrics = experiment.metrics["test"]
    rows = []
    for kind in ALL_MODEL_KINDS:
        m = test_metrics[kind]
        rows.append(
            {
                "model": kind,
                "roc_auc": m["discrimination"]["roc_auc"],
                "pr_auc": m["discrimination"]["pr_auc"],
                "brier_score": m["calibration"]["brier_score"],
                "ks_statistic": m["discrimination"]["ks_statistic"],
                "calibration_slope": m["calibration"]["calibration_slope"],
                "interpretability": (
                    "high (isotonic single-feature rule)"
                    if kind == "simple_rule"
                    else "high (linear coefficients/odds ratios)"
                    if kind == "logistic_regression"
                    else "low (non-linear ensemble)"
                    if kind == "hist_gradient_boosting"
                    else "trivial (constant prediction)"
                ),
                "artifact_kind": ".joblib (scikit-learn Pipeline)",
            }
        )
    table = pd.DataFrame(rows)
    table.to_csv(_table_path(experiment_id, "champion_challenger", repo_root), index=False)
    return table


def explain_experiment(experiment_id: str, *, repo_root: Path | None = None) -> None:
    repo_root = repo_root or Path.cwd()
    experiment = load_experiment(_experiment_path(experiment_id, repo_root))
    df, contract, _registry, _config, assignment = _load_experiment_data(experiment_id, repo_root)
    fitted = _reload_models(experiment_id, repo_root, experiment.seed)
    logistic = fitted[MAIN_CANDIDATE_KIND]

    features = engineer_features(df)
    target = df[contract.target_column]
    x_val = features.loc[assignment.validation_index]
    y_val = target.loc[assignment.validation_index]
    x_test = features.loc[assignment.test_index]
    y_test = target.loc[assignment.test_index]
    ids_test = df.loc[assignment.test_index, contract.identifier_column]

    coefficients = logistic_coefficients(logistic)
    pd.DataFrame([c.to_dict() for c in coefficients]).to_csv(
        _table_path(experiment_id, "coefficients", repo_root), index=False
    )

    permutation = compute_permutation_importance(logistic, x_val, y_val)
    pd.DataFrame([p.to_dict() for p in permutation]).to_csv(
        _table_path(experiment_id, "permutation_importance", repo_root), index=False
    )

    top_features = [p.feature for p in permutation]
    pdp_curves = compute_partial_dependence(logistic, x_val, top_features)
    pdp_rows = []
    for curve in pdp_curves:
        for grid_value, prediction in zip(curve.grid_values, curve.average_prediction, strict=True):
            pdp_rows.append(
                {
                    "feature": curve.feature,
                    "grid_value": grid_value,
                    "average_prediction": prediction,
                }
            )
    pdp_path = _table_path(experiment_id, "partial_dependence", repo_root)
    pd.DataFrame(pdp_rows).to_csv(pdp_path, index=False)

    p_test = predict_proba_positive(logistic, x_test)
    threshold = _load_top10_threshold(experiment_id, repo_root)

    cases = select_representative_cases(
        y_test.reset_index(drop=True),
        p_test.reset_index(drop=True),
        ids_test.reset_index(drop=True),
        threshold,
    )
    explanation_rows = []
    for label, positional_idx in cases.items():
        row_id = ids_test.iloc[positional_idx]
        explanation = local_explanation(
            logistic,
            x_test.iloc[[positional_idx]],
            row_id,
            float(p_test.iloc[positional_idx]),
            int(y_test.iloc[positional_idx]),
            label,
            repo_root=repo_root,
        )
        explanation_rows.append(explanation.to_dict())
    (repo_root / TABLES_DIR / f"{experiment_id}__local_explanations.json").write_text(
        json.dumps(explanation_rows, indent=2), encoding="utf-8"
    )


def audit_groups_experiment(experiment_id: str, *, repo_root: Path | None = None) -> Experiment:
    repo_root = repo_root or Path.cwd()
    experiment = load_experiment(_experiment_path(experiment_id, repo_root))
    df, contract, _registry, config, assignment = _load_experiment_data(experiment_id, repo_root)
    fitted = _reload_models(experiment_id, repo_root, experiment.seed)
    logistic = fitted[MAIN_CANDIDATE_KIND]

    features = engineer_features(df)
    target = df[contract.target_column]
    x_test = features.loc[assignment.test_index]
    y_test = target.loc[assignment.test_index]
    p_test = predict_proba_positive(logistic, x_test)
    threshold = _load_top10_threshold(experiment_id, repo_root)

    audit = run_subgroup_audit(
        df, y_test, p_test, threshold=threshold, age_buckets=config.subgroup_audit["age_buckets"]
    )
    pd.DataFrame([m.to_dict() for m in audit.metrics]).to_csv(
        _table_path(experiment_id, "subgroup_audit", repo_root), index=False
    )

    updated = Experiment(**{**experiment.to_dict(), "subgroup_audit_summary": audit.to_dict()})
    write_experiment(updated, repo_root / EXPERIMENTS_DIR)
    return updated


def stress_test_experiment(experiment_id: str, *, repo_root: Path | None = None) -> Experiment:
    repo_root = repo_root or Path.cwd()
    experiment = load_experiment(_experiment_path(experiment_id, repo_root))
    df, contract, _registry, config, assignment = _load_experiment_data(experiment_id, repo_root)
    fitted = _reload_models(experiment_id, repo_root, experiment.seed)
    logistic = fitted[MAIN_CANDIDATE_KIND]

    features = engineer_features(df)
    target = df[contract.target_column]
    x_test = features.loc[assignment.test_index]
    y_test = target.loc[assignment.test_index]
    raw_test = df.loc[assignment.test_index]
    p_test = predict_proba_positive(logistic, x_test)
    threshold = _load_top10_threshold(experiment_id, repo_root)

    results = run_robustness_suite(
        logistic, raw_test, y_test, p_test, threshold=threshold, config=config
    )
    pd.DataFrame([r.to_dict() for r in results]).to_csv(
        _table_path(experiment_id, "robustness", repo_root), index=False
    )

    summary = {"perturbations": [r.to_dict() for r in results]}
    updated = Experiment(**{**experiment.to_dict(), "robustness_summary": summary})
    write_experiment(updated, repo_root / EXPERIMENTS_DIR)
    return updated


def register_experiment_model(
    experiment_id: str, model_id: str, *, repo_root: Path | None = None
) -> tuple[GateReport, ModelCandidateManifest | None]:
    repo_root = repo_root or Path.cwd()
    experiment = load_experiment(_experiment_path(experiment_id, repo_root))
    if experiment.status not in ("evaluated", "registered_candidate", "gates_failed"):
        raise ReportingError(
            f"Experiment '{experiment_id}' has not been evaluated yet (status={experiment.status})."
        )
    df, _contract, registry, config, assignment = _load_experiment_data(experiment_id, repo_root)
    fitted = _reload_models(experiment_id, repo_root, experiment.seed)
    logistic = fitted[MAIN_CANDIDATE_KIND]

    features = engineer_features(df)
    x_val = features.loc[assignment.validation_index]

    test_metrics = experiment.metrics["test"][MAIN_CANDIDATE_KIND]
    dummy_pr_auc = experiment.metrics["test"]["dummy_prior"]["discrimination"]["pr_auc"]
    simple_rule_pr_auc = experiment.metrics["test"]["simple_rule"]["discrimination"]["pr_auc"]
    stability_stdev = experiment.metrics["split_stability"]["roc_auc_stdev"]

    subgroup_audit_completed = bool(experiment.subgroup_audit_summary)
    calibration_acceptable = bool(experiment.calibration.get("selected_method"))

    gate_report = evaluate_gates(
        dummy_pr_auc=dummy_pr_auc,
        simple_rule_pr_auc=simple_rule_pr_auc,
        candidate_pr_auc=test_metrics["discrimination"]["pr_auc"],
        candidate_roc_auc=test_metrics["discrimination"]["roc_auc"],
        no_leakage_detected=not experiment.warnings,
        calibration_acceptable=calibration_acceptable,
        split_stability_roc_auc_stdev=stability_stdev,
        subgroup_audit_completed=subgroup_audit_completed,
        artifact_validated=True,
        config=config,
    )

    manifest: ModelCandidateManifest | None = None
    if gate_report.eligible:
        p_val = predict_proba_positive(logistic, x_val)
        cuts = [float(q) for q in np.quantile(p_val.to_numpy(), [0.25, 0.5, 0.75])]
        manifest = register_model_candidate(
            logistic,
            model_id=model_id,
            experiment_id=experiment_id,
            output_dir=repo_root / "reports" / "modeling" / "models",
            feature_registry_version=registry.registry_version,
            test_metrics=test_metrics,
            limitations=[
                "Historical public benchmark (UCI, Taiwan, 2005) - not a Brazilian population.",
                "Behavioral early-warning model for an existing account - not an origination "
                "score.",
                "Not suitable for real lending decisions.",
            ],
            risk_band_cuts=cuts,
        )

    status = "registered_candidate" if gate_report.eligible else "gates_failed"
    updated = Experiment(
        **{
            **experiment.to_dict(),
            "status": status,
            "artifact_hash": manifest.artifact_sha256 if manifest else None,
        }
    )
    write_experiment(updated, repo_root / EXPERIMENTS_DIR)
    (repo_root / TABLES_DIR / f"{experiment_id}__gates.json").write_text(
        json.dumps(gate_report.to_dict(), indent=2), encoding="utf-8"
    )
    return gate_report, manifest


# --- Figures (Phase 8 section 29) -----------------------------------------
#
# Requires matplotlib (`credlens[analysis]`) in addition to `credlens
# [modeling]` - the same combination `credlens analysis run` already
# needs, never a new plotting dependency of its own.


def _require_matplotlib() -> Any:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ReportingError(
            "Figure generation needs matplotlib - install with "
            "'uv sync --extra analysis --extra modeling'."
        ) from exc
    return plt


def _watermark_and_save(fig: Any, path: Path) -> Path:
    from credlens.modeling.provenance import MODEL_LAB_PROVENANCE_LABEL_EN

    fig.text(0.5, 0.01, MODEL_LAB_PROVENANCE_LABEL_EN, ha="center", fontsize=7, color="dimgray")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    return path


def generate_figures(experiment_id: str, *, repo_root: Path | None = None) -> list[Path]:
    """Produces the 16 figures Phase 8 section 29 requires, reading ONLY
    from tables already written by `evaluate_experiment`/
    `explain_experiment`/`audit_groups_experiment`/`stress_test_
    experiment` - never recomputing a metric a figure just illustrates."""
    plt = _require_matplotlib()
    from sklearn.calibration import calibration_curve
    from sklearn.metrics import precision_recall_curve, roc_curve

    repo_root = repo_root or Path.cwd()
    experiment = load_experiment(_experiment_path(experiment_id, repo_root))
    figures_dir = repo_root / FIGURES_DIR
    paths: list[Path] = []

    def _save(fig: Any, name: str) -> None:
        paths.append(_watermark_and_save(fig, figures_dir / f"{experiment_id}__{name}.png"))
        plt.close(fig)

    predictions_test = pd.read_csv(_table_path(experiment_id, "predictions_test", repo_root))
    y_test = predictions_test["y_true"].to_numpy()
    p_test = predictions_test[MAIN_CANDIDATE_KIND].to_numpy()

    # 1. Prevalence by split
    fig, ax = plt.subplots(figsize=(5, 4))
    val_prev = experiment.metrics["test"][MAIN_CANDIDATE_KIND]["prevalence"]
    ax.bar(["test"], [val_prev], color="#1f5fa8")
    ax.set_ylabel("Default prevalence")
    ax.set_title(f"Prevalence (n={len(y_test)}) - historical benchmark, not a live portfolio")
    _save(fig, "01_prevalence")

    # 2. ROC curve
    fpr, tpr, _ = roc_curve(y_test, p_test)
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot(fpr, tpr, color="#1f5fa8", label="Logistic regression (test)")
    ax.plot([0, 1], [0, 1], "--", color="gray", label="Random")
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.set_title("ROC curve")
    ax.legend()
    _save(fig, "02_roc_curve")

    # 3. Precision-recall curve
    precision, recall, _ = precision_recall_curve(y_test, p_test)
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot(recall, precision, color="#6a3d9a")
    ax.axhline(val_prev, linestyle="--", color="gray", label="No-skill baseline (prevalence)")
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_title("Precision-recall curve")
    ax.legend()
    _save(fig, "03_precision_recall_curve")

    # 4. Calibration curve
    frac_pos, mean_pred = calibration_curve(y_test, p_test, n_bins=10, strategy="quantile")
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot(mean_pred, frac_pos, marker="o", color="#0e7c7b", label="Model")
    ax.plot([0, 1], [0, 1], "--", color="gray", label="Perfectly calibrated")
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Observed event rate")
    ax.set_title("Calibration curve (test)")
    ax.legend()
    _save(fig, "04_calibration_curve")

    decile = pd.DataFrame(
        experiment.metrics["test"][MAIN_CANDIDATE_KIND]["ranking"]["decile_table"]
    )

    # 5. Lift chart
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(decile["decile"], decile["lift"], color="#e6842e")
    ax.axhline(1.0, linestyle="--", color="gray")
    ax.set_xlabel("Decile (1 = highest predicted risk)")
    ax.set_ylabel("Lift")
    ax.set_title("Lift by decile")
    _save(fig, "05_lift_chart")

    # 6. Cumulative gains
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(
        decile["cumulative_population_share"],
        decile["cumulative_capture_rate"],
        marker="o",
        color="#1f5fa8",
    )
    ax.plot([0, 1], [0, 1], "--", color="gray", label="Random")
    ax.set_xlabel("Cumulative population share")
    ax.set_ylabel("Cumulative capture rate")
    ax.set_title("Cumulative gains")
    ax.legend()
    _save(fig, "06_cumulative_gains")

    # 7. Event rate by decile
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(decile["decile"], decile["event_rate"], color="#8b1a1a")
    ax.axhline(val_prev, linestyle="--", color="gray", label="Overall prevalence")
    ax.set_xlabel("Decile (1 = highest predicted risk)")
    ax.set_ylabel("Observed event rate")
    ax.set_title("Event rate by decile")
    ax.legend()
    _save(fig, "07_event_rate_by_decile")

    # 8. Confusion matrix at the top_10_pct operating point
    cm = experiment.metrics["test"][MAIN_CANDIDATE_KIND]["threshold_dependent"]
    matrix = np.array(
        [[cm["true_negative"], cm["false_positive"]], [cm["false_negative"], cm["true_positive"]]]
    )
    fig, ax = plt.subplots(figsize=(4.5, 4))
    ax.imshow(matrix, cmap="Blues")
    for (i, j), value in np.ndenumerate(matrix):
        ax.text(j, i, str(value), ha="center", va="center")
    ax.set_xticks([0, 1], ["Predicted 0", "Predicted 1"])
    ax.set_yticks([0, 1], ["Actual 0", "Actual 1"])
    ax.set_title(f"Confusion matrix (threshold={cm['threshold']:.3f})")
    _save(fig, "08_confusion_matrix")

    # 9. Champion/challenger comparison
    champ_path = _table_path(experiment_id, "champion_challenger", repo_root)
    if champ_path.is_file():
        champ = pd.read_csv(champ_path)
        fig, ax = plt.subplots(figsize=(7, 4))
        width = 0.35
        x = np.arange(len(champ))
        ax.bar(x - width / 2, champ["roc_auc"], width, label="ROC-AUC", color="#1f5fa8")
        ax.bar(x + width / 2, champ["pr_auc"], width, label="PR-AUC", color="#e6842e")
        ax.set_xticks(x, champ["model"], rotation=20, ha="right")
        ax.set_title("Champion/challenger comparison (test)")
        ax.legend()
        _save(fig, "09_champion_challenger")

    # 10. Coefficients / odds ratios
    coef_path = _table_path(experiment_id, "coefficients", repo_root)
    if coef_path.is_file():
        coefs = pd.read_csv(coef_path).head(10).iloc[::-1]
        fig, ax = plt.subplots(figsize=(7, 5))
        colors = ["#8b1a1a" if v > 0 else "#0e7c7b" for v in coefs["coefficient"]]
        ax.barh(coefs["feature"], coefs["coefficient"], color=colors)
        ax.set_xlabel("Standardized logistic coefficient")
        ax.set_title("Logistic regression coefficients (top 10 by magnitude)")
        _save(fig, "10_coefficients")

    # 11. Permutation importance
    perm_path = _table_path(experiment_id, "permutation_importance", repo_root)
    if perm_path.is_file():
        perm = pd.read_csv(perm_path).head(10).iloc[::-1]
        fig, ax = plt.subplots(figsize=(7, 5))
        ax.barh(
            perm["feature"], perm["mean_importance"], xerr=perm["stdev_importance"], color="#1f5fa8"
        )
        ax.set_xlabel("Permutation importance (average precision)")
        ax.set_title("Permutation importance (top 10)")
        _save(fig, "11_permutation_importance")

    # 12. Partial dependence (small multiples)
    pdp_path = _table_path(experiment_id, "partial_dependence", repo_root)
    if pdp_path.is_file():
        pdp = pd.read_csv(pdp_path)
        features = list(pdp["feature"].unique())[:5]
        fig, axes = plt.subplots(1, len(features), figsize=(4 * len(features), 3.5), squeeze=False)
        for ax, feature in zip(axes[0], features, strict=True):
            curve = pdp[pdp["feature"] == feature]
            ax.plot(curve["grid_value"], curve["average_prediction"], color="#6a3d9a")
            ax.set_title(feature, fontsize=9)
            ax.set_xlabel("Feature value")
            ax.set_ylabel("Avg. predicted P(default)")
        fig.suptitle("Partial dependence (association, not causation)")
        _save(fig, "12_partial_dependence")

    # 13. Local explanations (one representative high-risk case)
    local_path = repo_root / TABLES_DIR / f"{experiment_id}__local_explanations.json"
    if local_path.is_file():
        cases = json.loads(local_path.read_text(encoding="utf-8"))
        case = next((c for c in cases if c["case_label"] == "high_risk"), cases[0])
        reasons = case["reason_codes"]
        fig, ax = plt.subplots(figsize=(6, 4))
        colors = ["#8b1a1a" if r["contribution"] > 0 else "#0e7c7b" for r in reasons]
        ax.barh(
            [r["feature"] for r in reasons][::-1],
            [r["contribution"] for r in reasons][::-1],
            color=colors[::-1],
        )
        ax.set_xlabel("Contribution to the linear score")
        ax.set_title(f"Local explanation - {case['case_label']} ({case['pseudonymous_id']})")
        _save(fig, "13_local_explanation")

    # 14. Subgroup performance
    subgroup_path = _table_path(experiment_id, "subgroup_audit", repo_root)
    if subgroup_path.is_file():
        subgroup = pd.read_csv(subgroup_path).dropna(subset=["roc_auc"])
        fig, ax = plt.subplots(figsize=(8, 4.5))
        colors = [
            "#6b7280" if c == "insufficient" else "#1f5fa8"
            for c in subgroup["sample_classification"]
        ]
        labels = [
            f"{a}={g} (n={n})"
            for a, g, n in zip(subgroup["attribute"], subgroup["group"], subgroup["n"], strict=True)
        ]
        ax.barh(labels, subgroup["roc_auc"], color=colors)
        ax.set_xlabel("ROC-AUC")
        ax.set_title("Subgroup diagnostics - not a compliance assessment")
        _save(fig, "14_subgroup_performance")

    # 15. Stress test
    robustness_path = _table_path(experiment_id, "robustness", repo_root)
    if robustness_path.is_file():
        robustness = pd.read_csv(robustness_path)
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.barh(robustness["kind"], robustness["pr_auc_degradation"], color="#e6842e")
        ax.set_xlabel("PR-AUC degradation vs. unperturbed test set")
        ax.set_title("Robustness under controlled perturbations (technical, not a crisis forecast)")
        _save(fig, "15_stress_test")

    # 16. Seed stability
    stability_path = _table_path(experiment_id, "split_stability", repo_root)
    if stability_path.is_file():
        stability = pd.read_csv(stability_path)
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.scatter(stability["seed"], stability["roc_auc"], color="#1f5fa8")
        ax.axhline(stability["roc_auc"].mean(), linestyle="--", color="gray", label="Mean")
        ax.set_xlabel("Split seed")
        ax.set_ylabel("Test ROC-AUC")
        ax.set_title("Stability across independent split seeds")
        ax.legend()
        _save(fig, "16_seed_stability")

    return paths


# --- Model cards / technical reports / manifest (Phase 8 sections 30, 31, 33) --


REPORTS_DIR = Path("reports/modeling")

_METADATA_ONLY_KEYS = frozenset({"created_at_utc"})


def _content_fingerprint(payload: dict[str, Any]) -> str:
    """Excludes execution-time metadata (timestamps) from the hash so two
    runs of the SAME configuration produce the SAME fingerprint - Phase 8
    section 33's reproducibility requirement, mirroring Phase 7 gate E's
    content-vs-metadata distinction."""
    cleaned = {k: v for k, v in payload.items() if k not in _METADATA_ONLY_KEYS}
    return hashlib.sha256(json.dumps(cleaned, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReportContext:
    experiment: Experiment
    contract: TargetContract
    gate_report: dict[str, Any] | None
    model_manifest: dict[str, Any] | None
    champion_challenger: list[dict[Any, Any]]
    negative_controls: list[dict[Any, Any]]


def _gather_report_context(
    experiment_id: str, model_id: str | None, repo_root: Path
) -> ReportContext:
    experiment = load_experiment(_experiment_path(experiment_id, repo_root))
    contract = load_target_contract(repo_root)

    gate_path = repo_root / TABLES_DIR / f"{experiment_id}__gates.json"
    gate_report = json.loads(gate_path.read_text(encoding="utf-8")) if gate_path.is_file() else None

    model_manifest = None
    if model_id:
        manifest_path = repo_root / "reports" / "modeling" / "models" / f"{model_id}.manifest.json"
        if manifest_path.is_file():
            model_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    champ_path = _table_path(experiment_id, "champion_challenger", repo_root)
    champion_challenger = (
        pd.read_csv(champ_path).to_dict(orient="records") if champ_path.is_file() else []
    )

    controls_path = _table_path(experiment_id, "negative_controls", repo_root)
    negative_controls = (
        pd.read_csv(controls_path).to_dict(orient="records") if controls_path.is_file() else []
    )

    return ReportContext(
        experiment=experiment,
        contract=contract,
        gate_report=gate_report,
        model_manifest=model_manifest,
        champion_challenger=champion_challenger,
        negative_controls=negative_controls,
    )


def generate_model_card(
    experiment_id: str, model_id: str | None, language: str, *, repo_root: Path | None = None
) -> str:
    repo_root = repo_root or Path.cwd()
    ctx = _gather_report_context(experiment_id, model_id, repo_root)
    exp = ctx.experiment
    test_metrics = exp.metrics.get("test", {}).get(MAIN_CANDIDATE_KIND, {})
    disc = test_metrics.get("discrimination", {})
    cal = test_metrics.get("calibration", {})
    status_line = (
        f"**Status**: {ctx.model_manifest['status'] if ctx.model_manifest else exp.status}"
    )
    cal_slope = cal.get("calibration_slope", "n/a")
    cal_intercept = cal.get("calibration_intercept", "n/a")
    cal_method = exp.calibration.get("selected_method", "n/a")
    cal_reason = exp.calibration.get("reason", "")
    champ_table_ref = f"reports/modeling/tables/{experiment_id}__champion_challenger.csv"
    limitations_pt = (
        ctx.model_manifest["limitations"]
        if ctx.model_manifest
        else ["Modelo não registrado - gates não satisfeitos ou registro não executado."]
    )
    limitations_en = (
        ctx.model_manifest["limitations"]
        if ctx.model_manifest
        else ["Not registered - gates not satisfied or registration not run."]
    )
    limitations_pt_block = "\n".join("- " + item for item in limitations_pt)
    limitations_en_block = "\n".join("- " + item for item in limitations_en)

    if language == "pt-BR":
        return f"""# Model Card - Modelo Comportamental de Alerta Antecipado (Phase 8)

{status_line}

## Nome e versão
- Experimento: `{exp.experiment_id}`
- Modelo: `{model_id or "(não registrado)"}`
- Registro de features: v{exp.feature_registry_version}

## Finalidade
{ctx.contract.name_pt_br}

## Uso pretendido
Diagnóstico técnico/estudo de caso de um modelo comportamental de alerta antecipado de
inadimplência, sobre um benchmark público histórico (UCI, Taiwan, 2005), demonstrando
rigor metodológico (leakage, calibração, incerteza, auditoria de subgrupo, robustez).

## Usos proibidos
- Decisão de concessão de crédito (origination) - o dataset não suporta essa framing.
- Aprovação/recusa automática, pricing, limite de crédito.
- PD regulatória, LGD, EAD, otimização por lucro.
- Qualquer alegação de conformidade legal/fair-lending.
- **{NOT_SUITABLE_PT_BR}**

## Dataset
- Fonte: `{ctx.contract.source_id}` (hash `{exp.dataset_hash[:16]}...`)
- População: clientes de cartão de crédito, Taiwan, 2005 (não é população brasileira).
- Prevalência observada: {test_metrics.get("prevalence", "n/d")}

## Target
Coluna `{ctx.contract.target_column}` - inadimplência no mês seguinte à janela de 6 meses.

## Split
Hash combinado do split: `{exp.split_hash[:16]}...` (seed={exp.seed}, 60/20/20 estratificado).

## Features
{len(exp.feature_set)} features comportamentais engenheiradas (ver
`config/modeling/feature_registry.yml`) - nenhum atributo demográfico usado no treino.

## Atributos excluídos
SEXO, EDUCAÇÃO, ESTADO CIVIL, IDADE - apenas auditoria pós-hoc
(`credlens.modeling.subgroup_audit`).

## Modelos e seleção
{exp.estimator}. Comparação completa em `{champ_table_ref}`.

## Métricas (teste, bloqueado)
- ROC-AUC: {disc.get("roc_auc", "n/d")}
- PR-AUC: {disc.get("pr_auc", "n/d")}
- KS: {disc.get("ks_statistic", "n/d")}
- Brier: {cal.get("brier_score", "n/d")}
- Calibration slope/intercept: {cal_slope} / {cal_intercept}

## Uso do holdout
**Holdout de avaliação congelado, reutilizado em fases documentadas de validação** - não
"nunca tocado" nem "aberto uma única vez". O split nunca foi alterado e as previsões de
teste permanecem congeladas (nenhum ajuste original usou o teste), mas o mesmo teste foi
consultado repetidamente entre as Fases 8-10 (comparação de modelos, métricas, robustez,
subgrupo, threshold, candidato/challenger). Ver seção 6 de
`reports/model_validation/validation_report.pt-BR.md` para a divulgação completa e o
risco de adaptação indireta em qualquer modelo remediado.

## Calibração
Método selecionado: `{cal_method}`. {cal_reason}

## Thresholds
{exp.threshold_policy}

## Incerteza
Ver `reports/modeling/tables/{experiment_id}__bootstrap.json` (bootstrap estratificado) e
`{experiment_id}__split_stability.csv` (múltiplas seeds de split).

## Auditoria de subgrupo
Ver seção "Fairness and subgroup diagnostics - not a compliance assessment" em
`reports/modeling/tables/{experiment_id}__subgroup_audit.csv`. Não é certificação de
fairness nem avaliação de conformidade legal.

## Interpretabilidade
Coeficientes/odds ratios, permutation importance, partial dependence e reason codes
descritivos - ver `reports/modeling/tables/{experiment_id}__coefficients.csv`,
`{experiment_id}__permutation_importance.csv`, `{experiment_id}__local_explanations.json`.
Reason codes são governados por `config/model_validation/reason_codes.yml` (Fase 10,
gate E): apenas features com direção estável e VIF aceitável geram reason code em
linguagem causal ("allowed"); features redundantes/de baixa magnitude podem aparecer
apenas em linguagem matemática, nunca causal ("conditional"); features com inversão de
sinal frequente ou interpretação individual inadequada nunca aparecem ("prohibited").

## Robustez
Ver `reports/modeling/tables/{experiment_id}__robustness.csv` - testes técnicos de
perturbação, não previsão de crise real.

## Limitações
{limitations_pt_block}

## Riscos
Dataset histórico, de outro país/época; risco de generalização indevida para o
portfólio sintético do CredLens ou para qualquer instituição real.

## Governança
{SEPARATION_NOTICE_PT_BR}

## Reprodução
`uv run credlens model train/evaluate/explain/audit-groups/stress-test/register/report`
com o mesmo `--experiment-id` e seed.

## Manutenção futura
Nenhuma promoção automática a "champion"/"production". Reavaliação obrigatória se o
registro de features, o contrato de target ou a fonte mudarem de versão.

**{NOT_SUITABLE_PT_BR}**
"""

    return f"""# Model Card - Behavioral Early-Warning Model (Phase 8)

{status_line}

## Name and version
- Experiment: `{exp.experiment_id}`
- Model: `{model_id or "(not registered)"}`
- Feature registry: v{exp.feature_registry_version}

## Purpose
{ctx.contract.name_en}

## Intended use
A technical/case-study diagnostic of a behavioral early-warning default model on a
historical public benchmark (UCI, Taiwan, 2005), demonstrating methodological rigor
(leakage controls, calibration, uncertainty, subgroup audit, robustness).

## Prohibited uses
- Credit-granting (origination) decisions - the dataset structurally does not support
  that framing (see `docs/target_and_leakage_audit.md`).
- Automated approve/reject, pricing, credit-limit decisions.
- Regulatory PD, LGD, EAD, profit optimization.
- Any legal/fair-lending compliance claim.
- **{NOT_SUITABLE_EN}**

## Dataset
- Source: `{ctx.contract.source_id}` (hash `{exp.dataset_hash[:16]}...`)
- Population: Taiwanese credit card clients, 2005 (not a Brazilian population).
- Observed prevalence: {test_metrics.get("prevalence", "n/a")}

## Target
Column `{ctx.contract.target_column}` - default in the month following the 6-month window.

## Split
Combined split hash: `{exp.split_hash[:16]}...` (seed={exp.seed}, stratified 60/20/20).

## Features
{len(exp.feature_set)} engineered behavioral features (see
`config/modeling/feature_registry.yml`) - no demographic attribute used in training.

## Excluded attributes
SEX, EDUCATION, MARRIAGE, AGE - post-hoc audit only
(`credlens.modeling.subgroup_audit`).

## Models and selection
{exp.estimator}. Full comparison in `{champ_table_ref}`.

## Metrics (locked test set)
- ROC-AUC: {disc.get("roc_auc", "n/a")}
- PR-AUC: {disc.get("pr_auc", "n/a")}
- KS: {disc.get("ks_statistic", "n/a")}
- Brier: {cal.get("brier_score", "n/a")}
- Calibration slope/intercept: {cal_slope} / {cal_intercept}

## Holdout usage
**Frozen evaluation holdout reused across documented validation phases** - not "untouched"
and not "opened only once". The split has never been altered and the test predictions
remain frozen (no original tuning ever used the test set), but this same test set has been
repeatedly consulted across Phases 8-10 (model comparison, metrics, robustness, subgroup
audit, threshold validation, candidate/challenger comparison). See section 6 of
`reports/model_validation/validation_report.md` for the full disclosure and the
indirect-adaptation risk carried by any remediated model.

## Calibration
Selected method: `{cal_method}`. {cal_reason}

## Thresholds
{exp.threshold_policy}

## Uncertainty
See `reports/modeling/tables/{experiment_id}__bootstrap.json` (stratified bootstrap) and
`{experiment_id}__split_stability.csv` (multiple split seeds).

## Subgroup audit
See "Fairness and subgroup diagnostics - not a compliance assessment" in
`reports/modeling/tables/{experiment_id}__subgroup_audit.csv`. Not a fairness
certification, not a legal compliance assessment.

## Interpretability
Coefficients/odds ratios, permutation importance, partial dependence, and descriptive
reason codes - see `reports/modeling/tables/{experiment_id}__coefficients.csv`,
`{experiment_id}__permutation_importance.csv`, `{experiment_id}__local_explanations.json`.
Reason codes are governed by `config/model_validation/reason_codes.yml` (Phase 10 gate
E): only features with a stable direction and acceptable VIF generate a causal-language
reason code (`allowed`); redundant/low-magnitude features may appear only in
mathematical, never causal, language (`conditional`); features with frequent sign
inversion or an uninterpretable individual effect never appear (`prohibited`).

## Robustness
See `reports/modeling/tables/{experiment_id}__robustness.csv` - technical perturbation
tests, not a real-crisis forecast.

## Limitations
{limitations_en_block}

## Risks
Historical dataset from a different country/era; risk of improper generalization to the
CredLens synthetic portfolio or to any real institution.

## Governance
{SEPARATION_NOTICE_EN}

## Reproduction
`uv run credlens model train/evaluate/explain/audit-groups/stress-test/register/report`
with the same `--experiment-id` and seed.

## Future maintenance
No automatic promotion to "champion"/"production". Mandatory re-evaluation if the
feature registry, target contract, or source dataset version changes.

**{NOT_SUITABLE_EN}**
"""


def generate_technical_report(
    experiment_id: str, language: str, *, repo_root: Path | None = None
) -> str:
    repo_root = repo_root or Path.cwd()
    ctx = _gather_report_context(experiment_id, None, repo_root)
    exp = ctx.experiment
    champ_lines = "\n".join(
        f"| {row['model']} | {row['roc_auc']} | {row['pr_auc']} | {row['brier_score']} | "
        f"{row['ks_statistic']} |"
        for row in ctx.champion_challenger
    )
    controls_lines = "\n".join(
        f"| {row['name']} | {row['passed']} | {row['detail']} |" for row in ctx.negative_controls
    )
    gate_lines = "\n".join(
        f"| {g['name']} | {g['passed']} | {g['detail']} |"
        for g in (ctx.gate_report["gates"] if ctx.gate_report else [])
    )
    eligible_line = ctx.gate_report["reason"] if ctx.gate_report else "Gates not yet evaluated."

    if language == "pt-BR":
        return f"""# Relatório Técnico - Modelo Comportamental de Alerta Antecipado (Phase 8)

## 1. Problema
{ctx.contract.name_pt_br}

## 2. Fonte
`{ctx.contract.source_id}`, hash `{exp.dataset_hash}`.

## 3. Auditoria
Ver `reports/data_audit/` (Phase 2) e `credlens model data-audit` (reprodução).

## 4. Target
Coluna `{exp.target_column}`, ver `config/modeling/behavioral_default.yml`.

## 5. Features
{", ".join(exp.feature_set)}

## 6. Controles de leakage
| Controle | Passou | Detalhe |
|---|---|---|
{controls_lines}

## 7. Split
Seed {exp.seed}, hash combinado `{exp.split_hash}`.

## 8. Baselines, 9. Tuning, 10. Calibração
Estimador principal: {exp.estimator}. Hiperparâmetros: {json.dumps(exp.hyperparameters)}.
Calibração: {exp.calibration.get("selected_method")}.

## 11. Avaliação (teste bloqueado) / 12. Operating points / 13. Incerteza
Ver tabelas `reports/modeling/tables/{experiment_id}__*.csv` e
`{experiment_id}__bootstrap.json`. **Holdout de avaliação congelado, reutilizado em fases
documentadas de validação** - o split e as previsões de teste nunca mudaram, mas o mesmo
teste foi consultado repetidamente entre as Fases 8-10 (ver seção 6 de
`reports/model_validation/validation_report.pt-BR.md` para a divulgação completa).

## 14. Interpretabilidade / 15. Diagnóstico de subgrupo / 16. Robustez
Ver `{experiment_id}__coefficients.csv`, `{experiment_id}__subgroup_audit.csv`,
`{experiment_id}__robustness.csv`.

## 17. Comparação champion/challenger
| Modelo | ROC-AUC | PR-AUC | Brier | KS |
|---|---|---|---|---|
{champ_lines}

## 18. Gates de registro
| Gate | Passou | Detalhe |
|---|---|---|
{gate_lines}

**Resultado**: {eligible_line}

## 19. Limitações
{SEPARATION_NOTICE_PT_BR} {NOT_SUITABLE_PT_BR}

## 20. Reprodução
`uv run credlens model train --experiment-id {experiment_id} --seed {exp.seed}`, seguido de
`evaluate`, `compare`, `explain`, `audit-groups`, `stress-test`, `register`, `report`.
"""

    return f"""# Technical Report - Behavioral Early-Warning Model (Phase 8)

## 1. Problem
{ctx.contract.name_en}

## 2. Source
`{ctx.contract.source_id}`, hash `{exp.dataset_hash}`.

## 3. Audit
See `reports/data_audit/` (Phase 2) and `credlens model data-audit` (reproduction).

## 4. Target
Column `{exp.target_column}`, see `config/modeling/behavioral_default.yml`.

## 5. Features
{", ".join(exp.feature_set)}

## 6. Leakage controls
| Control | Passed | Detail |
|---|---|---|
{controls_lines}

## 7. Split
Seed {exp.seed}, combined hash `{exp.split_hash}`.

## 8. Baselines, 9. Tuning, 10. Calibration
Main estimator: {exp.estimator}. Hyperparameters: {json.dumps(exp.hyperparameters)}.
Calibration: {exp.calibration.get("selected_method")}.

## 11. Evaluation (locked test) / 12. Operating points / 13. Uncertainty
See tables `reports/modeling/tables/{experiment_id}__*.csv` and
`{experiment_id}__bootstrap.json`. **Frozen evaluation holdout reused across documented
validation phases** - the split and test predictions have never changed, but this same
test set has been repeatedly consulted across Phases 8-10 (see section 6 of
`reports/model_validation/validation_report.md` for the full disclosure).

## 14. Interpretability / 15. Subgroup diagnostics / 16. Robustness
See `{experiment_id}__coefficients.csv`, `{experiment_id}__subgroup_audit.csv`,
`{experiment_id}__robustness.csv`.

## 17. Champion/challenger comparison
| Model | ROC-AUC | PR-AUC | Brier | KS |
|---|---|---|---|---|
{champ_lines}

## 18. Registration gates
| Gate | Passed | Detail |
|---|---|---|
{gate_lines}

**Result**: {eligible_line}

## 19. Limitations
{SEPARATION_NOTICE_EN} {NOT_SUITABLE_EN}

## 20. Reproduction
`uv run credlens model train --experiment-id {experiment_id} --seed {exp.seed}`, followed by
`evaluate`, `compare`, `explain`, `audit-groups`, `stress-test`, `register`, `report`.
"""


def write_reports(
    experiment_id: str, model_id: str | None, *, repo_root: Path | None = None
) -> dict[str, Path]:
    repo_root = repo_root or Path.cwd()
    out_dir = repo_root / REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}
    for filename, content in (
        ("model_card.md", generate_model_card(experiment_id, model_id, "en", repo_root=repo_root)),
        (
            "model_card.pt-BR.md",
            generate_model_card(experiment_id, model_id, "pt-BR", repo_root=repo_root),
        ),
        (
            "technical_report.md",
            generate_technical_report(experiment_id, "en", repo_root=repo_root),
        ),
        (
            "technical_report.pt-BR.md",
            generate_technical_report(experiment_id, "pt-BR", repo_root=repo_root),
        ),
    ):
        path = out_dir / filename
        path.write_text(content, encoding="utf-8")
        written[filename] = path

    manifest = {
        "experiment_id": experiment_id,
        "model_id": model_id,
        "package_version": dependency_versions()["credlens"],
        "reports_written": sorted(written.keys()),
        "generated_at_utc": _now_iso(),
    }
    manifest["content_fingerprint"] = _content_fingerprint(
        {k: v for k, v in manifest.items() if k != "generated_at_utc"}
    )
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    written["manifest.json"] = manifest_path
    return written


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


NOT_SUITABLE_EN = "Not suitable for real lending decisions."
NOT_SUITABLE_PT_BR = "Não é adequado para decisões reais de concessão de crédito."


def _separation_notices() -> tuple[str, str]:
    from credlens.modeling.provenance import SEPARATION_NOTICE_EN, SEPARATION_NOTICE_PT_BR

    return SEPARATION_NOTICE_EN, SEPARATION_NOTICE_PT_BR


SEPARATION_NOTICE_EN, SEPARATION_NOTICE_PT_BR = _separation_notices()
