"""Baseline models (Phase 8 sections 11.1, 11.2) - comparison points the
logistic regression and challenger must beat, not candidates for
registration themselves.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.dummy import DummyClassifier
from sklearn.isotonic import IsotonicRegression

DELINQUENCY_RULE_FEATURE = "max_delinquency_status"


def build_dummy_prior() -> DummyClassifier:
    """Always predicts the training set's observed class prior - the
    absolute floor: a model must beat this to justify existing."""
    return DummyClassifier(strategy="prior")


def build_dummy_stratified(seed: int) -> DummyClassifier:
    """Predicts by drawing from the training class distribution -
    included because it is a useful PR-AUC floor is a distinct rule from
    the prior baseline."""
    return DummyClassifier(strategy="stratified", random_state=seed)


class SimpleDelinquencyRule(BaseEstimator, ClassifierMixin):  # type: ignore[misc]
    """A fully transparent, single-feature operational baseline: an
    isotonic (monotonic, so "worse delinquency history never lowers
    predicted risk" is guaranteed by construction, not just observed) fit
    of the target against `max_delinquency_status` alone. This is a
    comparison point for the interpretable/challenger models, never a
    candidate for registration itself (Phase 8 section 11.2)."""

    def __init__(self) -> None:
        self._isotonic: IsotonicRegression | None = None
        self.classes_ = np.array([0, 1])

    def _column(self, x: pd.DataFrame | np.ndarray) -> np.ndarray:
        if isinstance(x, pd.DataFrame):
            return x[DELINQUENCY_RULE_FEATURE].to_numpy(dtype=float)
        return np.asarray(x)[:, 0].astype(float)

    def fit(self, x: pd.DataFrame | np.ndarray, y: pd.Series | np.ndarray) -> SimpleDelinquencyRule:
        column = self._column(x)
        self._isotonic = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        self._isotonic.fit(column, np.asarray(y, dtype=float))
        return self

    def predict_proba(self, x: pd.DataFrame | np.ndarray) -> np.ndarray:
        if self._isotonic is None:
            raise RuntimeError("SimpleDelinquencyRule must be fit before predict_proba.")
        column = self._column(x)
        p1 = self._isotonic.predict(column)
        return np.column_stack([1.0 - p1, p1])

    def predict(self, x: pd.DataFrame | np.ndarray) -> np.ndarray:
        return (self.predict_proba(x)[:, 1] >= 0.5).astype(int)

    def get_params(self, deep: bool = True) -> dict[str, Any]:
        return {}

    def set_params(self, **params: Any) -> SimpleDelinquencyRule:
        return self
