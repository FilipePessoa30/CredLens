"""Cross-validated hyperparameter tuning on TRAIN ONLY (Phase 8 section
12) - `credlens.modeling.splitting`'s validation/test partitions are
never passed into this module. `GridSearchCV`'s internal folds are cut
from `x_train`/`y_train` alone.

Both grids are deliberately small (documented, not "busca enorme"):
logistic regression sweeps 4 values of `C`; the challenger sweeps 2x2
values of `max_leaf_nodes`/`learning_rate`. Everything runs at
`n_jobs=1` end to end - Phase 8 section 12's "prevencao de nested
parallelism" - `HistGradientBoostingClassifier` has no `n_jobs`
parameter of its own; its histogram-building step threads internally via
OpenMP, whose effective thread count is recorded in the experiment
registry via `threadpoolctl`, not silently left undocumented.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

import pandas as pd
from sklearn.model_selection import GridSearchCV, StratifiedKFold

from credlens.modeling.contracts import EvaluationConfig, FeatureRegistry, TargetContract
from credlens.modeling.leakage import assert_training_frame_is_clean
from credlens.modeling.training import (
    N_JOBS,
    FittedModel,
    ModelKind,
    build_pipeline,
    default_estimator,
)


@dataclass(frozen=True)
class TuningResult:
    model_kind: ModelKind
    best_params: dict[str, Any]
    best_average_precision: float
    best_roc_auc: float
    cv_folds: int
    cv_results: list[dict[str, Any]]
    fitted: FittedModel
    tuning_seconds: float


def _run_grid_search(
    model_kind: ModelKind,
    param_grid: dict[str, list[Any]],
    cv_folds: int,
    x_train: pd.DataFrame,
    y_train: pd.Series,
    seed: int,
) -> TuningResult:
    estimator = default_estimator(model_kind, seed=seed)
    pipeline = build_pipeline(model_kind, estimator)
    prefixed_grid = {f"estimator__{k}": v for k, v in param_grid.items()}

    search = GridSearchCV(
        pipeline,
        param_grid=prefixed_grid,
        scoring={"average_precision": "average_precision", "roc_auc": "roc_auc"},
        refit="average_precision",
        cv=StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=seed),
        n_jobs=N_JOBS,
    )
    started = perf_counter()
    search.fit(x_train, y_train)
    elapsed = perf_counter() - started

    cv_results = []
    results = search.cv_results_
    for i in range(len(results["params"])):
        cv_results.append(
            {
                "params": {
                    k.replace("estimator__", ""): v for k, v in results["params"][i].items()
                },
                "mean_average_precision": round(
                    float(results["mean_test_average_precision"][i]), 6
                ),
                "std_average_precision": round(float(results["std_test_average_precision"][i]), 6),
                "mean_roc_auc": round(float(results["mean_test_roc_auc"][i]), 6),
            }
        )

    best_index = search.best_index_
    fitted = FittedModel(
        model_kind=model_kind,
        pipeline=search.best_estimator_,
        hyperparameters={k.replace("estimator__", ""): v for k, v in search.best_params_.items()},
        seed=seed,
        n_jobs=N_JOBS,
        fit_seconds=elapsed,
        feature_columns=list(x_train.columns),
    )
    return TuningResult(
        model_kind=model_kind,
        best_params=fitted.hyperparameters,
        best_average_precision=float(results["mean_test_average_precision"][best_index]),
        best_roc_auc=float(results["mean_test_roc_auc"][best_index]),
        cv_folds=cv_folds,
        cv_results=cv_results,
        fitted=fitted,
        tuning_seconds=elapsed,
    )


def tune_logistic_regression(
    x_train: pd.DataFrame,
    y_train: pd.Series,
    config: EvaluationConfig,
    *,
    registry: FeatureRegistry,
    contract: TargetContract,
) -> TuningResult:
    assert_training_frame_is_clean(list(x_train.columns), registry, contract)
    tuning_cfg = config.tuning
    lr_cfg = tuning_cfg["logistic_regression"]
    grid = {"C": lr_cfg["C"]}
    return _run_grid_search(
        "logistic_regression",
        grid,
        int(tuning_cfg["cv_folds"]),
        x_train,
        y_train,
        int(tuning_cfg["seed"]),
    )


def tune_hist_gradient_boosting(
    x_train: pd.DataFrame,
    y_train: pd.Series,
    config: EvaluationConfig,
    *,
    registry: FeatureRegistry,
    contract: TargetContract,
) -> TuningResult:
    assert_training_frame_is_clean(list(x_train.columns), registry, contract)
    tuning_cfg = config.tuning
    hgb_cfg = tuning_cfg["hist_gradient_boosting"]
    grid = {"max_leaf_nodes": hgb_cfg["max_leaf_nodes"], "learning_rate": hgb_cfg["learning_rate"]}
    return _run_grid_search(
        "hist_gradient_boosting",
        grid,
        int(hgb_cfg["cv_folds"]),
        x_train,
        y_train,
        int(tuning_cfg["seed"]),
    )
