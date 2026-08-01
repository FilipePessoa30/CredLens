"""Phase 10 gate D - post-validation remediation of the redundant/
unstable logistic-regression coefficients Phase 9's coefficient_audit
found in EXP_behavioral_default_v1/MODEL_behavioral_default_v1: 9 of 18
features not fully stable (4 `redundant`, including 2 VIF-infinite
pairs; 5 `unstable_direction`) - see
`config/model_validation/remediation_policy.yml` for the documented,
per-feature decision.

Builds up to THREE additional experiments for comparison, always reusing
the SAME locked split as the original (`split_hash="reused_from:
<original>"` - the test set is never re-split, consistent with gate C's
holdout-reuse disclosure):

  - VIF-reduced (`credlens.model_validation.reporting.
    build_reduced_experiment`, Phase 9's existing pure-VIF iterative
    elimination) - a comparison baseline, not gate D's deliverable.
  - Stability-reduced (`stability_reduced_feature_set` below) -
    mechanically drops every feature the ORIGINAL 18-feature model's
    coefficient_audit classified `redundant`/`unstable_direction`, with
    NO pairwise judgment. Deliberately kept as a second, naive comparison
    baseline: it drops BOTH members of every redundant pair (losing
    delinquency-count, bill-amount, and payment-amount information
    entirely), which is exactly why gate D needed manual review instead
    of a mechanical rule.
  - Final remediated (`final_remediated_feature_set` below, driven by
    `remediation_policy.yml`) - THE gate D deliverable: for each
    redundant/collinear pair, keeps the more interpretable, more
    intuitively-signed member and drops the other; drops standalone
    unstable features outright (no substitute exists for them).

None of this ever overwrites EXP_behavioral_default_v1/
MODEL_behavioral_default_v1. Per gate C, any model built here is a
"post-validation remediation model" - the frozen holdout has already
been repeatedly observed across Phases 8-10, so an unusually LARGE
improvement over v1 is treated as a red flag (possible indirect
adaptation), not a win - see `decide_remediation`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np
import pandas as pd
import yaml

from credlens.data.checksums import compute_sha256
from credlens.model_validation.coefficient_audit import (
    bootstrap_coefficient_samples,
    classify_coefficients,
    cv_fold_coefficient_samples,
    regularization_sensitivity_samples,
)
from credlens.model_validation.collinearity import run_collinearity_audit
from credlens.model_validation.evidence import load_validation_config
from credlens.model_validation.reporting import (
    EXPERIMENTS_DIR,
    MODELING_TABLES_DIR,
    build_reduced_experiment,
)
from credlens.modeling.contracts import (
    load_evaluation_config,
    load_feature_registry,
    load_target_contract,
)
from credlens.modeling.data import load_uci_default_credit
from credlens.modeling.evaluation import full_metrics, roc_auc
from credlens.modeling.features import FEATURE_COLUMNS, engineer_features
from credlens.modeling.registry import (
    Experiment,
    dependency_versions,
    load_experiment,
    write_experiment,
)
from credlens.modeling.splitting import (
    apply_split_assignment_table,
    create_split,
    load_split_assignment_table,
)
from credlens.modeling.training import fit_model, predict_proba_positive
from credlens.modeling.tuning import tune_logistic_regression

REMEDIATION_POLICY_PATH = Path("config/model_validation/remediation_policy.yml")
VALIDATION_TABLES_DIR = Path("reports/model_validation/tables")
MODELS_DIR = Path("reports/modeling/models")

RemediationDecisionLabel = Literal[
    "remediation_candidate", "remediation_rejected", "requires_new_external_validation"
]

_OUTPUT_SCHEMA = {
    "pseudonymous_record_id": "string",
    "predicted_default_probability": "float64",
    "risk_band": "string",
    "model_version": "string",
    "scoring_timestamp": "string",
    "input_schema_version": "string",
}


class RemediationError(Exception):
    """Raised when a remediation build/comparison/registration step cannot run."""


# --- Policy loading and feature-set derivation ------------------------------


def load_remediation_policy(repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root or Path.cwd()
    path = repo_root / REMEDIATION_POLICY_PATH
    if not path.is_file():
        raise RemediationError(f"Remediation policy not found at '{path}'.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return dict(raw)


def final_remediated_feature_set(policy: dict[str, Any]) -> list[str]:
    decisions = {row["feature"]: row for row in policy["final_remediated_feature_decisions"]}
    missing = set(FEATURE_COLUMNS) - set(decisions)
    if missing:
        raise RemediationError(
            f"remediation_policy.yml is missing a decision for: {sorted(missing)}"
        )
    return [f for f in FEATURE_COLUMNS if decisions[f]["action"] == "keep"]


def stability_reduced_feature_set(classification_table: pd.DataFrame) -> list[str]:
    """Mechanical comparison baseline (gate D model #3) - drop every
    feature the ORIGINAL model's coefficient_audit classified `redundant`
    or `unstable_direction`, no pairwise judgment. See module docstring
    for why this is intentionally naive."""
    dropped_categories = {"redundant", "unstable_direction"}
    is_dropped = classification_table["category"].isin(dropped_categories)
    dropped = set(classification_table.loc[is_dropped, "feature"])
    return [f for f in FEATURE_COLUMNS if f not in dropped]


# --- Building a reduced experiment (shared by stability-reduced and final) -


def _build_experiment_from_feature_set(
    original_experiment_id: str,
    new_experiment_id: str,
    kept_features: list[str],
    *,
    estimator_label: str,
    selection_method: str,
    seed: int = 42,
    repo_root: Path | None = None,
) -> Experiment:
    repo_root = repo_root or Path.cwd()
    contract = load_target_contract(repo_root)
    registry = load_feature_registry(repo_root)
    config = load_evaluation_config(repo_root)
    validation_config = load_validation_config(repo_root)
    df = load_uci_default_credit(repo_root)

    split_table = load_split_assignment_table(
        repo_root / EXPERIMENTS_DIR / original_experiment_id / "split_assignment.csv"
    )
    assignment = apply_split_assignment_table(df, split_table, id_column=contract.identifier_column)
    features = engineer_features(df)
    target = df[contract.target_column]

    x_train = features.loc[assignment.train_index, kept_features]
    y_train = target.loc[assignment.train_index]
    x_val = features.loc[assignment.validation_index, kept_features]
    y_val = target.loc[assignment.validation_index]
    x_test = features.loc[assignment.test_index, kept_features]
    y_test = target.loc[assignment.test_index]

    tuned = tune_logistic_regression(x_train, y_train, config, registry=registry, contract=contract)
    p_val = predict_proba_positive(tuned.fitted, x_val)
    p_test = predict_proba_positive(tuned.fitted, x_test)

    exp_dir = repo_root / EXPERIMENTS_DIR / new_experiment_id
    models_dir = exp_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(tuned.fitted.pipeline, models_dir / "logistic_regression.joblib")

    ids_val = df.loc[assignment.validation_index, contract.identifier_column]
    ids_test = df.loc[assignment.test_index, contract.identifier_column]
    pd.DataFrame(
        {
            "id": ids_val.to_numpy(),
            "y_true": y_val.to_numpy(),
            "logistic_regression": p_val.to_numpy(),
        }
    ).to_csv(
        repo_root / MODELING_TABLES_DIR / f"{new_experiment_id}__predictions_val.csv", index=False
    )
    pd.DataFrame(
        {
            "id": ids_test.to_numpy(),
            "y_true": y_test.to_numpy(),
            "logistic_regression": p_test.to_numpy(),
        }
    ).to_csv(
        repo_root / MODELING_TABLES_DIR / f"{new_experiment_id}__predictions_test.csv", index=False
    )

    # Re-audit collinearity/coefficient stability on the SURVIVING feature
    # set - removing correlated features changes VIF/stability for the
    # ones that remain (e.g. months_delinquent_count's VIF was 56.83 only
    # because consecutive_months_delinquent was also present). The
    # decision function below must use these NEW numbers, never the
    # original 18-feature model's classification.
    collinearity_cfg = validation_config.collinearity
    collinearity = run_collinearity_audit(x_train, collinearity_cfg)

    estimator_step = tuned.fitted.pipeline.named_steps["estimator"]
    original_coefficients = dict(
        zip(kept_features, [float(c) for c in estimator_step.coef_[0]], strict=True)
    )
    bootstrap_samples = bootstrap_coefficient_samples(
        x_train,
        y_train,
        n_resamples=int(collinearity_cfg["coefficient_bootstrap_n_resamples"]),
        seed=int(collinearity_cfg["coefficient_bootstrap_seed"]),
    )
    cv_samples = cv_fold_coefficient_samples(
        x_train, y_train, n_folds=int(collinearity_cfg["cv_folds_for_stability"]), seed=42
    )
    regularization_samples = regularization_sensitivity_samples(
        x_train, y_train, c_grid=list(collinearity_cfg["regularization_sensitivity_grid"])
    )
    classification = classify_coefficients(
        original_coefficients,
        bootstrap_samples,
        cv_samples,
        regularization_samples,
        collinearity,
        collinearity_cfg,
    )
    pd.DataFrame([c.to_dict() for c in classification]).to_csv(
        repo_root / VALIDATION_TABLES_DIR / f"{new_experiment_id}__coefficient_classification.csv",
        index=False,
    )
    pd.DataFrame([row.to_dict() for row in collinearity.vif_table]).to_csv(
        repo_root / VALIDATION_TABLES_DIR / f"{new_experiment_id}__vif.csv", index=False
    )

    stability_seeds = list(config.uncertainty["split_stability"]["seeds"])[:3]
    stability_roc_aucs = []
    for stability_seed in stability_seeds:
        fresh_assignment = create_split(
            df,
            id_column=contract.identifier_column,
            target_column=contract.target_column,
            config=config,
            seed=stability_seed,
        )
        fresh_x_train = features.loc[fresh_assignment.train_index, kept_features]
        fresh_y_train = target.loc[fresh_assignment.train_index]
        fresh_x_test = features.loc[fresh_assignment.test_index, kept_features]
        fresh_y_test = target.loc[fresh_assignment.test_index]
        fresh_fitted = fit_model(
            "logistic_regression",
            fresh_x_train,
            fresh_y_train,
            registry=registry,
            contract=contract,
            seed=stability_seed,
        )
        fresh_p_test = predict_proba_positive(fresh_fitted, fresh_x_test)
        stability_roc_aucs.append(roc_auc(fresh_y_test, fresh_p_test))

    experiment = Experiment(
        experiment_id=new_experiment_id,
        dataset_id="uci-default-credit",
        dataset_hash=contract.acquired_hash_sha256,
        split_hash="reused_from:" + original_experiment_id,
        target_column=contract.target_column,
        feature_set=kept_features,
        feature_registry_version=registry.registry_version,
        preprocessing=f"median imputation + standardization ({selection_method} feature set)",
        estimator=f"logistic_regression ({estimator_label})",
        hyperparameters=tuned.best_params,
        seed=seed,
        cv_description=(
            f"StratifiedKFold(n_splits={tuned.cv_folds}), scoring=average_precision, train-only"
        ),
        metrics={
            "validation": full_metrics(y_val, p_val),
            "test": full_metrics(y_test, p_test),
            "collinearity": collinearity.to_dict(),
            "coefficient_classification": [c.to_dict() for c in classification],
            "split_stability_roc_auc": {
                "seeds": stability_seeds,
                "values": stability_roc_aucs,
                "mean": float(np.mean(stability_roc_aucs)),
                "stdev": (
                    float(np.std(stability_roc_aucs, ddof=1))
                    if len(stability_roc_aucs) > 1
                    else 0.0
                ),
            },
        },
        calibration={
            "selected_method": "none",
            "reason": f"Not recalibrated for the {selection_method} model.",
        },
        threshold_policy="Illustrative review-capacity scenario (never profit-optimized)",
        subgroup_audit_summary={},
        robustness_summary={},
        artifact_hash=None,
        dependency_versions=dependency_versions(),
        status="evaluated",
        warnings=[],
    )
    write_experiment(experiment, repo_root / EXPERIMENTS_DIR)
    return experiment


def build_stability_reduced_experiment(
    original_experiment_id: str,
    new_experiment_id: str,
    *,
    seed: int = 42,
    repo_root: Path | None = None,
) -> Experiment:
    repo_root = repo_root or Path.cwd()
    classification_path = (
        repo_root
        / VALIDATION_TABLES_DIR
        / f"{original_experiment_id}__coefficient_classification.csv"
    )
    if not classification_path.is_file():
        raise RemediationError(
            f"No coefficient classification table at '{classification_path}' - run "
            "'credlens model validate-independent' on the original experiment first."
        )
    classification_table = pd.read_csv(classification_path)
    kept = stability_reduced_feature_set(classification_table)
    return _build_experiment_from_feature_set(
        original_experiment_id,
        new_experiment_id,
        kept,
        estimator_label="stability-reduced, mechanical - comparison baseline only",
        selection_method="stability-reduced (mechanical)",
        seed=seed,
        repo_root=repo_root,
    )


def build_final_remediated_experiment(
    original_experiment_id: str,
    new_experiment_id: str,
    *,
    seed: int = 42,
    repo_root: Path | None = None,
) -> Experiment:
    repo_root = repo_root or Path.cwd()
    policy = load_remediation_policy(repo_root)
    kept = final_remediated_feature_set(policy)
    return _build_experiment_from_feature_set(
        original_experiment_id,
        new_experiment_id,
        kept,
        estimator_label="final remediated - documented pairwise feature selection, gate D",
        selection_method="final remediated",
        seed=seed,
        repo_root=repo_root,
    )


# --- Five-model comparison ---------------------------------------------------


def _bootstrap_roc_auc_width(
    y_true: np.ndarray, p: np.ndarray, *, n_resamples: int = 200, seed: int = 20260728
) -> float:
    """Width (p97.5 - p2.5) of a stratified bootstrap of ROC-AUC on
    already-frozen predictions - the "bootstrap stability" axis of the
    gate D comparison, computed uniformly for all 5 models (never a
    retrain)."""
    rng = np.random.default_rng(seed)
    positive_idx = np.flatnonzero(y_true == 1)
    negative_idx = np.flatnonzero(y_true == 0)
    values = []
    for _ in range(n_resamples):
        idx = np.concatenate(
            [
                rng.choice(positive_idx, size=len(positive_idx), replace=True),
                rng.choice(negative_idx, size=len(negative_idx), replace=True),
            ]
        )
        try:
            values.append(roc_auc(pd.Series(y_true[idx]), pd.Series(p[idx])))
        except ValueError:
            continue
    if len(values) < 2:
        return float("nan")
    return float(np.percentile(values, 97.5) - np.percentile(values, 2.5))


def _measure_latency_ms(pipeline: Any, x: pd.DataFrame, *, n_repeats: int = 5) -> float:
    durations = []
    for _ in range(n_repeats):
        started = time.perf_counter()
        pipeline.predict_proba(x)
        durations.append((time.perf_counter() - started) * 1000.0)
    return float(sum(durations) / len(durations))


@dataclass(frozen=True)
class RemediationComparisonRow:
    model: str
    n_features: int
    pr_auc: float
    roc_auc: float
    brier_score: float
    log_loss: float
    ks_statistic: float
    calibration_slope: float | None
    max_vif: float | None
    condition_number: float | None
    mean_sign_flip_rate: float | None
    split_stability_roc_auc_stdev: float | None
    bootstrap_roc_auc_width: float
    scoring_latency_ms: float
    artifact_size_bytes: int
    reason_code_eligible_features: int | None
    dropped_features: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "n_features": self.n_features,
            "pr_auc": round(self.pr_auc, 6),
            "roc_auc": round(self.roc_auc, 6),
            "brier_score": round(self.brier_score, 6),
            "log_loss": round(self.log_loss, 6),
            "ks_statistic": round(self.ks_statistic, 6),
            "calibration_slope": (
                round(self.calibration_slope, 6) if self.calibration_slope is not None else None
            ),
            "max_vif": round(self.max_vif, 4) if self.max_vif is not None else None,
            "condition_number": (
                round(self.condition_number, 4) if self.condition_number is not None else None
            ),
            "mean_sign_flip_rate": (
                round(self.mean_sign_flip_rate, 4) if self.mean_sign_flip_rate is not None else None
            ),
            "split_stability_roc_auc_stdev": (
                round(self.split_stability_roc_auc_stdev, 6)
                if self.split_stability_roc_auc_stdev is not None
                else None
            ),
            "bootstrap_roc_auc_width": round(self.bootstrap_roc_auc_width, 6),
            "scoring_latency_ms": round(self.scoring_latency_ms, 4),
            "artifact_size_bytes": self.artifact_size_bytes,
            "reason_code_eligible_features": self.reason_code_eligible_features,
            "dropped_features": self.dropped_features,
        }


def _row_from_reduced_experiment(
    model_label: str, experiment: Experiment, *, repo_root: Path
) -> RemediationComparisonRow:
    test = experiment.metrics["test"]
    disc = test["discrimination"]
    cal = test["calibration"]
    classification = experiment.metrics["coefficient_classification"]
    flip_rates = [row["bootstrap_sign_flip_rate"] for row in classification]
    n_eligible = sum(1 for row in classification if row["category"] == "stable_direction")
    vif_values = [row["vif"] for row in experiment.metrics["collinearity"]["vif_table"] if row["vif"] is not None]

    predictions = pd.read_csv(
        repo_root / MODELING_TABLES_DIR / f"{experiment.experiment_id}__predictions_test.csv"
    )
    y_arr = predictions["y_true"].to_numpy()
    p_arr = predictions["logistic_regression"].to_numpy()
    artifact_path = repo_root / EXPERIMENTS_DIR / experiment.experiment_id / "models" / "logistic_regression.joblib"
    pipeline = joblib.load(artifact_path)
    x_test_sample = pd.DataFrame(
        [dict.fromkeys(experiment.feature_set, 0.0)] * 5, columns=experiment.feature_set
    )

    dropped = [f for f in FEATURE_COLUMNS if f not in experiment.feature_set]
    return RemediationComparisonRow(
        model=model_label,
        n_features=len(experiment.feature_set),
        pr_auc=disc["pr_auc"],
        roc_auc=disc["roc_auc"],
        brier_score=cal["brier_score"],
        log_loss=cal["log_loss"],
        ks_statistic=disc["ks_statistic"],
        calibration_slope=cal["calibration_slope"],
        max_vif=max(vif_values) if vif_values else None,
        condition_number=experiment.metrics["collinearity"]["condition_number"],
        mean_sign_flip_rate=float(np.mean(flip_rates)) if flip_rates else None,
        split_stability_roc_auc_stdev=experiment.metrics["split_stability_roc_auc"]["stdev"],
        bootstrap_roc_auc_width=_bootstrap_roc_auc_width(y_arr, p_arr),
        scoring_latency_ms=_measure_latency_ms(pipeline, x_test_sample),
        artifact_size_bytes=artifact_path.stat().st_size,
        reason_code_eligible_features=n_eligible,
        dropped_features=dropped,
    )


def compare_five_models(
    original_experiment_id: str,
    *,
    vif_reduced_experiment_id: str,
    stability_reduced_experiment_id: str,
    final_remediated_experiment_id: str,
    repo_root: Path | None = None,
) -> list[RemediationComparisonRow]:
    """Gate D's 5-model comparison: original logistic (v1), VIF-reduced,
    stability-reduced, final remediated, HistGBM challenger - reusing
    `{original_experiment_id}__pareto_comparison.csv` (already produced by
    `credlens model compare-candidates`) for models 1 and 5 rather than
    recomputing metrics that already exist and are independently tested,
    and building fresh rows for models 2-4."""
    repo_root = repo_root or Path.cwd()
    pareto_path = repo_root / VALIDATION_TABLES_DIR / f"{original_experiment_id}__pareto_comparison.csv"
    if not pareto_path.is_file():
        raise RemediationError(
            f"No Pareto comparison table at '{pareto_path}' - run 'credlens model "
            "register-challenger' then 'credlens model compare-candidates' on the "
            "original experiment first."
        )
    pareto = pd.read_csv(pareto_path)
    original_row = pareto[pareto["model"] == "logistic_regression (candidate)"].iloc[0]
    challenger_row = pareto[pareto["model"] == "hist_gradient_boosting (challenger)"].iloc[0]

    original_classification_path = (
        repo_root / VALIDATION_TABLES_DIR / f"{original_experiment_id}__coefficient_classification.csv"
    )
    original_classification = pd.read_csv(original_classification_path)
    original_vif_path = repo_root / VALIDATION_TABLES_DIR / f"{original_experiment_id}__vif.csv"
    original_vif = pd.read_csv(original_vif_path)
    original_experiment = load_experiment(repo_root / EXPERIMENTS_DIR / f"{original_experiment_id}.json")

    original_predictions = pd.read_csv(
        repo_root / MODELING_TABLES_DIR / f"{original_experiment_id}__predictions_test.csv"
    )
    y_arr = original_predictions["y_true"].to_numpy()

    original_models_dir = repo_root / EXPERIMENTS_DIR / original_experiment_id / "models"
    logistic_pipeline = joblib.load(original_models_dir / "logistic_regression.joblib")
    challenger_pipeline = joblib.load(original_models_dir / "hist_gradient_boosting.joblib")
    x_sample = pd.DataFrame(
        [dict.fromkeys(FEATURE_COLUMNS, 0.0)] * 5, columns=list(FEATURE_COLUMNS)
    )

    row_original = RemediationComparisonRow(
        model="original logistic (v1)",
        n_features=len(FEATURE_COLUMNS),
        pr_auc=float(original_row["pr_auc"]),
        roc_auc=float(original_row["roc_auc"]),
        brier_score=float(original_row["brier_score"]),
        log_loss=float(original_row["log_loss"]),
        ks_statistic=float(original_row["ks_statistic"]),
        calibration_slope=float(original_row["calibration_slope"]),
        max_vif=float(original_vif["vif"].dropna().max()) if original_vif["vif"].notna().any() else None,
        condition_number=None,
        mean_sign_flip_rate=float(original_classification["bootstrap_sign_flip_rate"].mean()),
        split_stability_roc_auc_stdev=float(original_row["split_stability_roc_auc_stdev"]),
        bootstrap_roc_auc_width=_bootstrap_roc_auc_width(
            y_arr, original_predictions["logistic_regression"].to_numpy()
        ),
        scoring_latency_ms=_measure_latency_ms(logistic_pipeline, x_sample),
        artifact_size_bytes=int(original_row["artifact_size_bytes"]),
        reason_code_eligible_features=int(
            (original_classification["category"] == "stable_direction").sum()
        ),
        dropped_features=[],
    )
    row_challenger = RemediationComparisonRow(
        model="HistGBM (challenger)",
        n_features=len(FEATURE_COLUMNS),
        pr_auc=float(challenger_row["pr_auc"]),
        roc_auc=float(challenger_row["roc_auc"]),
        brier_score=float(challenger_row["brier_score"]),
        log_loss=float(challenger_row["log_loss"]),
        ks_statistic=float(challenger_row["ks_statistic"]),
        calibration_slope=float(challenger_row["calibration_slope"]),
        max_vif=None,
        condition_number=None,
        mean_sign_flip_rate=None,
        split_stability_roc_auc_stdev=float(challenger_row["split_stability_roc_auc_stdev"]),
        bootstrap_roc_auc_width=_bootstrap_roc_auc_width(
            y_arr, original_predictions["hist_gradient_boosting"].to_numpy()
        ),
        scoring_latency_ms=_measure_latency_ms(challenger_pipeline, x_sample),
        artifact_size_bytes=int(challenger_row["artifact_size_bytes"]),
        reason_code_eligible_features=None,
        dropped_features=[],
    )
    _ = original_experiment  # kept for parity/traceability, not otherwise needed

    vif_experiment = load_experiment(repo_root / EXPERIMENTS_DIR / f"{vif_reduced_experiment_id}.json")
    stability_experiment = load_experiment(
        repo_root / EXPERIMENTS_DIR / f"{stability_reduced_experiment_id}.json"
    )
    final_experiment = load_experiment(
        repo_root / EXPERIMENTS_DIR / f"{final_remediated_experiment_id}.json"
    )

    rows = [row_original]
    if "collinearity" in vif_experiment.metrics:
        rows.append(_row_from_reduced_experiment("VIF-reduced", vif_experiment, repo_root=repo_root))
    else:
        # build_reduced_experiment (Phase 9) doesn't re-run the coefficient
        # audit - report what it DOES have, with VIF/stability/reason-code
        # fields explicitly absent rather than guessed.
        test = vif_experiment.metrics["test"]
        disc, cal = test["discrimination"], test["calibration"]
        predictions = pd.read_csv(
            repo_root / MODELING_TABLES_DIR / f"{vif_reduced_experiment_id}__predictions_test.csv"
        )
        rows.append(
            RemediationComparisonRow(
                model="VIF-reduced",
                n_features=len(vif_experiment.feature_set),
                pr_auc=disc["pr_auc"],
                roc_auc=disc["roc_auc"],
                brier_score=cal["brier_score"],
                log_loss=cal["log_loss"],
                ks_statistic=disc["ks_statistic"],
                calibration_slope=cal["calibration_slope"],
                max_vif=None,
                condition_number=None,
                mean_sign_flip_rate=None,
                split_stability_roc_auc_stdev=vif_experiment.metrics["split_stability_roc_auc"][
                    "stdev"
                ],
                bootstrap_roc_auc_width=_bootstrap_roc_auc_width(
                    predictions["y_true"].to_numpy(), predictions["logistic_regression"].to_numpy()
                ),
                scoring_latency_ms=float("nan"),
                artifact_size_bytes=(
                    repo_root
                    / EXPERIMENTS_DIR
                    / vif_reduced_experiment_id
                    / "models"
                    / "logistic_regression_reduced.joblib"
                ).stat().st_size,
                reason_code_eligible_features=None,
                dropped_features=[f for f in FEATURE_COLUMNS if f not in vif_experiment.feature_set],
            )
        )
    rows.append(
        _row_from_reduced_experiment("Stability-reduced (mechanical)", stability_experiment, repo_root=repo_root)
    )
    rows.append(
        _row_from_reduced_experiment("Final remediated (gate D)", final_experiment, repo_root=repo_root)
    )
    rows.append(row_challenger)
    return rows


# --- Decision -----------------------------------------------------------


@dataclass(frozen=True)
class RemediationDecision:
    decision: RemediationDecisionLabel
    reason: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"decision": self.decision, "reason": self.reason, "evidence": self.evidence}


def decide_remediation(
    original_row: RemediationComparisonRow,
    final_row: RemediationComparisonRow,
    remediation_cfg: dict[str, Any],
) -> RemediationDecision:
    """Never treated as a promotion gate - `remediation_candidate` is the
    MOST favorable outcome this function can reach, never
    `validation_passed`/`candidate`/`production`. Three checks, in order:

    1. Did remediation actually fix what it targeted (max VIF among KEPT
       features below the action threshold, no kept feature with a
       bootstrap sign-flip rate at/above the unstable threshold, using
       the RE-AUDITED numbers on the reduced feature set)? If not ->
       `remediation_rejected` - a remediation that doesn't remediate.
    2. Is the change in PR-AUC/ROC-AUC vs. v1 IMPLAUSIBLY LARGE in the
       improvement direction? Since remediation only removes redundant/
       unstable coefficients (no new information is added), a genuinely
       large gain cannot be explained by that alone - given gate C's
       disclosure that this same frozen test set has been repeatedly
       observed across Phases 8-10, a suspiciously large improvement is
       treated as an indirect-adaptation risk signal, not a win ->
       `requires_new_external_validation`.
    3. Did remediation lose real predictive signal (PR-AUC/ROC-AUC
       degraded beyond the documented tolerance)? -> `remediation_rejected`.
    4. Otherwise -> `remediation_candidate`.
    """
    max_vif_threshold = float(remediation_cfg["max_vif_action_threshold"])
    max_flip_rate = float(remediation_cfg["max_kept_feature_sign_flip_rate"])
    max_degradation = float(remediation_cfg["max_pr_auc_degradation_vs_v1"])
    max_improvement = float(remediation_cfg["max_pr_auc_suspicious_improvement_vs_v1"])
    max_roc_degradation = float(remediation_cfg["max_roc_auc_degradation_vs_v1"])
    max_roc_improvement = float(remediation_cfg["max_roc_auc_suspicious_improvement_vs_v1"])

    evidence: dict[str, Any] = {
        "final_remediated": final_row.to_dict(),
        "original_v1": original_row.to_dict(),
        "thresholds": remediation_cfg,
    }

    structural_problems = []
    if final_row.max_vif is not None and final_row.max_vif >= max_vif_threshold:
        structural_problems.append(f"max VIF among kept features is {final_row.max_vif:.2f} (>= {max_vif_threshold})")
    if final_row.mean_sign_flip_rate is not None and final_row.mean_sign_flip_rate >= max_flip_rate:
        structural_problems.append(
            f"mean bootstrap sign-flip rate among kept features is "
            f"{final_row.mean_sign_flip_rate:.4f} (>= {max_flip_rate})"
        )
    if structural_problems:
        return RemediationDecision(
            decision="remediation_rejected",
            reason=(
                "The remediated feature set still shows structural problems it was meant "
                "to fix: " + "; ".join(structural_problems) + "."
            ),
            evidence=evidence,
        )

    pr_auc_delta = final_row.pr_auc - original_row.pr_auc
    roc_auc_delta = final_row.roc_auc - original_row.roc_auc
    evidence["pr_auc_delta_vs_v1"] = round(pr_auc_delta, 6)
    evidence["roc_auc_delta_vs_v1"] = round(roc_auc_delta, 6)

    if pr_auc_delta > max_improvement or roc_auc_delta > max_roc_improvement:
        return RemediationDecision(
            decision="requires_new_external_validation",
            reason=(
                f"The remediated model's PR-AUC/ROC-AUC improved over v1 by "
                f"{pr_auc_delta:+.4f}/{roc_auc_delta:+.4f} - larger than plausible from "
                "removing redundant/unstable coefficients alone (no new information was "
                "added). Given gate C's disclosure that this frozen test set has been "
                "repeatedly observed across Phases 8-10, this magnitude of improvement "
                "cannot be trusted without a fresh, independent external holdout."
            ),
            evidence=evidence,
        )

    if pr_auc_delta < -max_degradation or roc_auc_delta < -max_roc_degradation:
        return RemediationDecision(
            decision="remediation_rejected",
            reason=(
                f"The remediated model's PR-AUC/ROC-AUC degraded by {pr_auc_delta:+.4f}/"
                f"{roc_auc_delta:+.4f} relative to v1 - beyond the documented tolerance "
                f"(-{max_degradation}/-{max_roc_degradation}). Removing the dropped "
                "features cost real predictive signal."
            ),
            evidence=evidence,
        )

    return RemediationDecision(
        decision="remediation_candidate",
        reason=(
            f"Remediation resolved the structural problems (max VIF "
            f"{final_row.max_vif if final_row.max_vif is not None else 'n/a'}, mean sign-flip "
            f"rate {final_row.mean_sign_flip_rate:.4f}) while keeping PR-AUC/ROC-AUC within "
            f"{pr_auc_delta:+.4f}/{roc_auc_delta:+.4f} of v1 - a plausible, non-suspicious "
            "change. Never auto-promoted: v1 remains the official model; this is a "
            "post-validation remediation model requiring its own explicit registration."
        ),
        evidence=evidence,
    )


# --- Registration (separate from v1, never overwriting it) -----------------


def register_remediation_candidate(
    experiment_id: str, model_id: str, decision: RemediationDecisionLabel, *, repo_root: Path | None = None
) -> dict[str, Any]:
    """Registers the final-remediated pipeline under its OWN model_id,
    with `status` set to the Phase 10 gate D decision label - never
    `candidate`/`production`, and never touching
    MODEL_behavioral_default_v1's manifest."""
    if decision not in ("remediation_candidate", "remediation_rejected", "requires_new_external_validation"):
        raise RemediationError(f"Unknown remediation decision label '{decision}'.")
    repo_root = repo_root or Path.cwd()
    experiment = load_experiment(repo_root / EXPERIMENTS_DIR / f"{experiment_id}.json")
    models_dir = repo_root / EXPERIMENTS_DIR / experiment_id / "models"
    pipeline_path = models_dir / "logistic_regression.joblib"
    if not pipeline_path.is_file():
        raise RemediationError(f"No trained pipeline at '{pipeline_path}'.")

    output_dir = repo_root / MODELS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / f"{model_id}.joblib"
    pipeline = joblib.load(pipeline_path)
    joblib.dump(pipeline, artifact_path)
    artifact_hash = compute_sha256(artifact_path)

    test_metrics = experiment.metrics["test"]
    manifest = {
        "model_id": model_id,
        "status": decision,
        "experiment_id": experiment_id,
        "artifact_relative_path": artifact_path.name,
        "artifact_sha256": artifact_hash,
        "input_schema": dict.fromkeys(experiment.feature_set, "float64"),
        "output_schema": dict(_OUTPUT_SCHEMA),
        "benchmark_source_id": "uci-default-credit",
        "feature_registry_version": experiment.feature_registry_version,
        "test_metrics": test_metrics,
        "limitations": [
            "Historical public benchmark (UCI, Taiwan, 2005) - not a Brazilian population.",
            "Post-validation remediation model (Phase 10 gate D) - built AFTER the frozen "
            "test set had already been repeatedly observed across Phases 8-10; carries an "
            "indirect-adaptation risk. Never a new independent external validation.",
            "Not suitable for real lending decisions.",
        ],
        "risk_band_cuts": [],
    }
    manifest_path = output_dir / f"{model_id}.manifest.json"
    import json

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    from credlens.model_validation.lifecycle import record_transition

    record_transition(
        model_id,
        decision,
        evidence_ref=f"reports/modeling/models/{model_id}.manifest.json",
        gate_summary=f"Phase 10 gate D remediation decision: {decision}.",
        repo_root=repo_root,
    )
    return manifest


# --- Top-level orchestration (used by the `credlens model remediate` /
# `credlens model compare-remediation` CLI subcommands) -------------------


REMEDIATION_REPORTS_DIR = Path("reports/model_validation")


def run_remediation(
    original_experiment_id: str,
    new_experiment_id: str,
    *,
    model_id: str | None = None,
    seed: int = 42,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Builds all three comparison experiments (VIF-reduced, stability-
    reduced, final remediated), compares all 5 models, decides, registers
    the final remediated model under `model_id` ONLY if the decision is
    `remediation_candidate`, and writes the bilingual remediation report.
    Never touches `original_experiment_id`'s own artifacts."""
    repo_root = repo_root or Path.cwd()
    vif_reduced_id = f"{new_experiment_id}_vif_only"
    stability_reduced_id = f"{new_experiment_id}_stability_only"

    vif_experiment = build_reduced_experiment(
        original_experiment_id, vif_reduced_id, seed=seed, repo_root=repo_root
    )
    if vif_experiment is None:
        raise RemediationError(
            f"VIF elimination on '{original_experiment_id}' did not drop any feature - "
            "the VIF-reduced comparison baseline would be identical to v1 and is not "
            "meaningful; investigate before remediating."
        )
    build_stability_reduced_experiment(
        original_experiment_id, stability_reduced_id, seed=seed, repo_root=repo_root
    )
    build_final_remediated_experiment(
        original_experiment_id, new_experiment_id, seed=seed, repo_root=repo_root
    )

    rows = compare_five_models(
        original_experiment_id,
        vif_reduced_experiment_id=vif_reduced_id,
        stability_reduced_experiment_id=stability_reduced_id,
        final_remediated_experiment_id=new_experiment_id,
        repo_root=repo_root,
    )
    comparison_table = pd.DataFrame([r.to_dict() for r in rows])
    comparison_table.to_csv(
        repo_root / VALIDATION_TABLES_DIR / f"{new_experiment_id}__remediation_comparison.csv",
        index=False,
    )

    row_original = next(r for r in rows if r.model == "original logistic (v1)")
    row_final = next(r for r in rows if r.model == "Final remediated (gate D)")
    validation_config = load_validation_config(repo_root)
    decision = decide_remediation(row_original, row_final, validation_config.raw["remediation"])

    manifest: dict[str, Any] | None = None
    if decision.decision == "remediation_candidate" and model_id is not None:
        manifest = register_remediation_candidate(
            new_experiment_id, model_id, decision.decision, repo_root=repo_root
        )

    write_remediation_report(
        new_experiment_id, rows, decision, model_id=model_id if manifest is not None else None,
        repo_root=repo_root,
    )

    return {
        "vif_reduced_experiment_id": vif_reduced_id,
        "stability_reduced_experiment_id": stability_reduced_id,
        "final_remediated_experiment_id": new_experiment_id,
        "comparison": [r.to_dict() for r in rows],
        "decision": decision.to_dict(),
        "registered_model_id": model_id if manifest is not None else None,
    }


def _comparison_markdown_table(rows: list[RemediationComparisonRow]) -> str:
    header = (
        "| Model | Features | PR-AUC | ROC-AUC | Brier | Max VIF | Sign-flip | "
        "Split-stability std | Reason-code features |\n"
        "|---|---|---|---|---|---|---|---|---|"
    )
    lines = [header]
    for row in rows:
        max_vif_str = f"{row.max_vif:.2f}" if row.max_vif is not None else "n/a"
        flip_str = f"{row.mean_sign_flip_rate:.4f}" if row.mean_sign_flip_rate is not None else "n/a"
        stability_str = (
            f"{row.split_stability_roc_auc_stdev:.6f}"
            if row.split_stability_roc_auc_stdev is not None
            else "n/a"
        )
        reason_str = (
            str(row.reason_code_eligible_features)
            if row.reason_code_eligible_features is not None
            else "n/a"
        )
        lines.append(
            f"| {row.model} | {row.n_features} | {row.pr_auc:.4f} | {row.roc_auc:.4f} | "
            f"{row.brier_score:.4f} | {max_vif_str} | {flip_str} | {stability_str} | {reason_str} |"
        )
    return "\n".join(lines)


def write_remediation_report(
    new_experiment_id: str,
    rows: list[RemediationComparisonRow],
    decision: RemediationDecision,
    *,
    model_id: str | None,
    repo_root: Path | None = None,
) -> dict[str, Path]:
    repo_root = repo_root or Path.cwd()
    out_dir = repo_root / REMEDIATION_REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    table_md = _comparison_markdown_table(rows)
    registered_line_en = (
        f"Registered as `{model_id}` (status=`{decision.decision}`)."
        if model_id
        else "NOT registered as a model candidate (decision was not `remediation_candidate`, or "
        "no --model-id was given)."
    )
    registered_line_pt = (
        f"Registrado como `{model_id}` (status=`{decision.decision}`)."
        if model_id
        else "NÃO registrado como candidato a modelo (decisão não foi `remediation_candidate`, ou "
        "nenhum --model-id foi informado)."
    )

    en = f"""# Remediation Report (Phase 10 gate D)

## 1. Scope
Post-validation remediation of `EXP_behavioral_default_v1`'s redundant/unstable logistic
regression coefficients. Never overwrites `EXP_behavioral_default_v1`/
`MODEL_behavioral_default_v1`. Feature-selection decisions are documented in
`config/model_validation/remediation_policy.yml`.

## 2. Holdout reuse
Per gate C, this is a **post-validation remediation model**, never a new independent
external validation - the frozen test set has already been repeatedly observed across
Phases 8-10. See `reports/model_validation/validation_report.md` section 6 for the full
disclosure.

## 3. Five-model comparison
New experiment: `{new_experiment_id}`.

{table_md}

## 4. Decision
**{decision.decision}**

{decision.reason}

## 5. Registration
{registered_line_en}

## 6. Limitations
Historical public benchmark (UCI, Taiwan, 2005). Not a fairness certification, not a legal
compliance assessment. **Not suitable for real lending decisions.**
"""
    pt = f"""# Relatório de Remediação (Fase 10, gate D)

## 1. Escopo
Remediação pós-validação dos coeficientes redundantes/instáveis da regressão logística de
`EXP_behavioral_default_v1`. Nunca sobrescreve `EXP_behavioral_default_v1`/
`MODEL_behavioral_default_v1`. As decisões de seleção de features estão documentadas em
`config/model_validation/remediation_policy.yml`.

## 2. Reutilização do holdout
Conforme o gate C, este é um **modelo de remediação pós-validação**, nunca uma nova
validação externa independente - o conjunto de teste congelado já foi observado
repetidamente ao longo das Fases 8-10. Ver a seção 6 de
`reports/model_validation/validation_report.pt-BR.md` para a divulgação completa.

## 3. Comparação de 5 modelos
Novo experimento: `{new_experiment_id}`.

{table_md}

## 4. Decisão
**{decision.decision}**

{decision.reason}

## 5. Registro
{registered_line_pt}

## 6. Limitações
Benchmark público histórico (UCI, Taiwan, 2005). Não é certificação de fairness, nem
avaliação de conformidade legal. **Não é adequado para decisões reais de concessão de
crédito.**
"""
    written = {}
    for filename, content in (
        ("remediation_report.md", en),
        ("remediation_report.pt-BR.md", pt),
    ):
        path = out_dir / filename
        path.write_text(content, encoding="utf-8")
        written[filename] = path
    return written
