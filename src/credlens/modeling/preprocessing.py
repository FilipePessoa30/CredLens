"""Preprocessing pipelines for the Phase 8 estimators (Phase 8 section 11).

All 18 engineered features (`credlens.modeling.features.FEATURE_COLUMNS`)
are numeric by construction - no categorical encoding is needed for the
main model, since the only categorical raw columns (EDUCATION, MARRIAGE,
SEX) are `excluded_sensitive` and never reach training (see
`config/modeling/feature_registry.yml`). Imputation is still real, not
theatre: `credlens.modeling.robustness` injects missingness into an
otherwise complete dataset specifically to exercise it.
"""

from __future__ import annotations

from typing import Literal

from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ModelKind = Literal["logistic_regression", "hist_gradient_boosting"]


def build_preprocessing_pipeline(model_kind: ModelKind) -> Pipeline:
    """Median imputation for every model kind; standard scaling is added
    only for `logistic_regression` - tree-based `hist_gradient_boosting`
    needs no scaling and would gain nothing from it."""
    steps: list[tuple[str, object]] = [("imputer", SimpleImputer(strategy="median"))]
    if model_kind == "logistic_regression":
        steps.append(("scaler", StandardScaler()))
    pipeline = Pipeline(steps)
    # Keeps column names through every transform step (SimpleDelinquencyRule
    # in baselines.py reads a feature by NAME, not by position).
    return pipeline.set_output(transform="pandas")
