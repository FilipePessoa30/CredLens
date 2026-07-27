"""Assembles and fits the four required model levels (Phase 8 section 11)
behind a single, leakage-checked entry point.

Every `fit_model` call runs `credlens.modeling.leakage.assert_training_
frame_is_clean` first - this is the one place in the codebase a pipeline
is actually fit, so it is also the one place that check cannot be
skipped by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal

import pandas as pd
from sklearn.base import BaseEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from credlens.modeling.baselines import (
    SimpleDelinquencyRule,
    build_dummy_prior,
)
from credlens.modeling.contracts import FeatureRegistry, TargetContract
from credlens.modeling.leakage import assert_training_frame_is_clean
from credlens.modeling.preprocessing import build_preprocessing_pipeline

try:
    from sklearn.ensemble import HistGradientBoostingClassifier

    _HGB_AVAILABLE = True
except ImportError:  # pragma: no cover - scikit-learn always ships this class
    _HGB_AVAILABLE = False

ModelKind = Literal["dummy_prior", "simple_rule", "logistic_regression", "hist_gradient_boosting"]

MODEL_KINDS: tuple[ModelKind, ...] = (
    "dummy_prior",
    "simple_rule",
    "logistic_regression",
    "hist_gradient_boosting",
)

# A single thread everywhere - Phase 8 section 12 requires "prevencao de
# nested parallelism", and the dataset is small enough that parallelism
# would buy nothing measurable while making timing/determinism claims
# fuzzier.
N_JOBS = 1


@dataclass(frozen=True)
class FittedModel:
    model_kind: ModelKind
    pipeline: Pipeline
    hyperparameters: dict[str, Any]
    seed: int | None
    n_jobs: int
    fit_seconds: float
    feature_columns: list[str]


def default_estimator(model_kind: ModelKind, *, seed: int) -> BaseEstimator:
    if model_kind == "dummy_prior":
        return build_dummy_prior()
    if model_kind == "simple_rule":
        return SimpleDelinquencyRule()
    if model_kind == "logistic_regression":
        # scikit-learn's default penalty is already L2-equivalent - passing
        # `penalty=`/`n_jobs=` explicitly is deprecated as of this project's
        # pinned scikit-learn version (see uv.lock) and produces a
        # FutureWarning on every fit without changing behavior.
        return LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000, random_state=seed)
    if model_kind == "hist_gradient_boosting":
        if not _HGB_AVAILABLE:  # pragma: no cover
            raise ImportError("scikit-learn's HistGradientBoostingClassifier is unavailable.")
        return HistGradientBoostingClassifier(random_state=seed)
    raise ValueError(f"Unknown model_kind '{model_kind}'. Expected one of {MODEL_KINDS}.")


def build_pipeline(model_kind: ModelKind, estimator: BaseEstimator) -> Pipeline:
    if model_kind in ("dummy_prior",):
        return Pipeline([("estimator", estimator)])
    if model_kind == "simple_rule":
        # SimpleDelinquencyRule reads a single named column directly -
        # imputation still runs first so it never sees a NaN under
        # robustness-injected missingness.
        return Pipeline(
            [
                ("imputer", build_preprocessing_pipeline("hist_gradient_boosting")),
                ("estimator", estimator),
            ]
        )
    if model_kind in ("logistic_regression", "hist_gradient_boosting"):
        return Pipeline(
            [("preprocessing", build_preprocessing_pipeline(model_kind)), ("estimator", estimator)]
        )
    raise ValueError(f"Unknown model_kind '{model_kind}'.")


def fit_model(
    model_kind: ModelKind,
    x_train: pd.DataFrame,
    y_train: pd.Series,
    *,
    registry: FeatureRegistry,
    contract: TargetContract,
    estimator: BaseEstimator | None = None,
    seed: int = 42,
) -> FittedModel:
    """The single leakage-checked entry point for fitting any of the four
    model kinds. `x_train` must already be the engineered feature frame
    (`credlens.modeling.features.engineer_features` output) - never the
    raw UCI columns."""
    assert_training_frame_is_clean(list(x_train.columns), registry, contract)

    resolved_estimator = estimator or default_estimator(model_kind, seed=seed)
    pipeline = build_pipeline(model_kind, resolved_estimator)

    started = perf_counter()
    pipeline.fit(x_train, y_train)
    elapsed = perf_counter() - started

    hyperparameters = (
        resolved_estimator.get_params() if hasattr(resolved_estimator, "get_params") else {}
    )
    return FittedModel(
        model_kind=model_kind,
        pipeline=pipeline,
        hyperparameters={k: v for k, v in hyperparameters.items() if _is_json_safe(v)},
        seed=seed,
        n_jobs=N_JOBS,
        fit_seconds=elapsed,
        feature_columns=list(x_train.columns),
    )


def _is_json_safe(value: Any) -> bool:
    return isinstance(value, str | int | float | bool | type(None))


def predict_proba_positive(fitted: FittedModel, x: pd.DataFrame) -> pd.Series:
    """Predicted P(default) for every row - the only prediction surface
    the rest of the modeling package (evaluation, thresholds, batch
    scoring) is allowed to call."""
    proba = fitted.pipeline.predict_proba(x)[:, 1]
    return pd.Series(proba, index=x.index, name="predicted_default_probability")
