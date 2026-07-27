"""Probability calibration comparison (Phase 8 section 14) - fit using
ONLY train (via internal cross-validation), selected by looking at the
validation set, never the locked test set.

If no calibration method improves Brier score AND does not worsen
Expected Calibration Error versus the uncalibrated model, the
uncalibrated model is kept and that is recorded explicitly - "preserve o
modelo não calibrado e documente" is a real code path here, not an
afterthought.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
from sklearn.base import clone
from sklearn.calibration import CalibratedClassifierCV

from credlens.modeling.contracts import EvaluationConfig
from credlens.modeling.evaluation import (
    brier,
    calibration_intercept_slope,
    expected_calibration_error,
    logloss,
)
from credlens.modeling.training import FittedModel

_BRIER_IMPROVEMENT_TOLERANCE = 1e-4


@dataclass(frozen=True)
class CalibrationCandidate:
    method: str
    brier_score: float
    log_loss: float
    calibration_intercept: float
    calibration_slope: float
    expected_calibration_error: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "brier_score": round(self.brier_score, 6),
            "log_loss": round(self.log_loss, 6),
            "calibration_intercept": round(self.calibration_intercept, 6),
            "calibration_slope": round(self.calibration_slope, 6),
            "expected_calibration_error": round(self.expected_calibration_error, 6),
        }


@dataclass(frozen=True)
class CalibrationResult:
    selected_method: str
    reason: str
    candidates: list[CalibrationCandidate]
    pipelines: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_method": self.selected_method,
            "reason": self.reason,
            "candidates": [c.to_dict() for c in self.candidates],
        }

    @property
    def selected_pipeline(self) -> Any:
        return self.pipelines[self.selected_method]


def _score_candidate(
    method: str, pipeline: Any, x_val: pd.DataFrame, y_val: pd.Series
) -> CalibrationCandidate:
    proba = pd.Series(pipeline.predict_proba(x_val)[:, 1], index=x_val.index)
    intercept, slope = calibration_intercept_slope(y_val, proba)
    return CalibrationCandidate(
        method=method,
        brier_score=brier(y_val, proba),
        log_loss=logloss(y_val, proba),
        calibration_intercept=intercept,
        calibration_slope=slope,
        expected_calibration_error=expected_calibration_error(y_val, proba),
    )


def compare_calibration(
    fitted: FittedModel,
    x_train: pd.DataFrame,
    y_train: pd.Series,
    x_val: pd.DataFrame,
    y_val: pd.Series,
    config: EvaluationConfig,
) -> CalibrationResult:
    cal_cfg = config.calibration
    candidates: list[CalibrationCandidate] = []
    pipelines: dict[str, Any] = {"none": fitted.pipeline}
    candidates.append(_score_candidate("none", fitted.pipeline, x_val, y_val))

    n_positive = int(y_train.sum())
    for method in cal_cfg["methods"]:
        if method == "none":
            continue
        if method == "isotonic" and n_positive < int(cal_cfg["isotonic_minimum_positive_count"]):
            continue
        base = clone(fitted.pipeline)
        calibrated = CalibratedClassifierCV(
            estimator=base, method=method, cv=int(cal_cfg["cv_folds"])
        )
        calibrated.fit(x_train, y_train)
        pipelines[method] = calibrated
        candidates.append(_score_candidate(method, calibrated, x_val, y_val))

    none_candidate = next(c for c in candidates if c.method == "none")
    best = min(candidates, key=lambda c: c.brier_score)

    if (
        best.method != "none"
        and best.brier_score < none_candidate.brier_score - _BRIER_IMPROVEMENT_TOLERANCE
        and best.expected_calibration_error <= none_candidate.expected_calibration_error
    ):
        selected = best.method
        reason = (
            f"'{best.method}' calibration improved Brier score on validation "
            f"({best.brier_score:.6f} vs. {none_candidate.brier_score:.6f} uncalibrated) "
            "without worsening expected calibration error."
        )
    else:
        selected = "none"
        reason = (
            "No calibration method produced a consistent improvement over the uncalibrated "
            f"model on validation (best Brier {best.brier_score:.6f} vs. uncalibrated "
            f"{none_candidate.brier_score:.6f}) - the uncalibrated model is preserved."
        )

    return CalibrationResult(
        selected_method=selected, reason=reason, candidates=candidates, pipelines=pipelines
    )
