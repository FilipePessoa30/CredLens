"""Independent re-derivation of calibration metrics (Phase 9 sections 4,
10) - Brier score and log loss via plain numpy reductions (not
`sklearn.metrics.brier_score_loss`/`log_loss`), calibration slope/
intercept via `scipy.optimize.minimize` on a hand-written negative
log-likelihood (not `sklearn.linear_model.LogisticRegression`), and
Expected Calibration Error computed under BOTH equal-width and
equal-mass (quantile) binning, at multiple bin counts, to audit whether
the Phase 8 "no calibration needed" call is bin-count-dependent (section
10: "Verifique se... o ECE depende do número de bins").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from credlens.model_validation.discrimination import MetricComparison, compare_metric

_LOGIT_EPSILON = 1e-6


def independent_brier(y: pd.Series, p: pd.Series) -> float:
    y_arr = np.asarray(y, dtype=float)
    p_arr = np.asarray(p, dtype=float)
    return float(np.mean((p_arr - y_arr) ** 2))


def independent_log_loss(y: pd.Series, p: pd.Series) -> float:
    y_arr = np.asarray(y, dtype=float)
    p_arr = np.clip(np.asarray(p, dtype=float), _LOGIT_EPSILON, 1 - _LOGIT_EPSILON)
    return float(-np.mean(y_arr * np.log(p_arr) + (1 - y_arr) * np.log(1 - p_arr)))


def independent_calibration_slope_intercept(y: pd.Series, p: pd.Series) -> tuple[float, float]:
    """Fits `y ~ sigmoid(intercept + slope * logit(p))` by minimizing
    negative log-likelihood directly with `scipy.optimize.minimize`
    (BFGS) - an independent optimizer/entry point from
    `credlens.modeling.evaluation.calibration_intercept_slope`'s
    `sklearn.linear_model.LogisticRegression(C=np.inf)`."""
    y_arr = np.asarray(y, dtype=float)
    p_arr = np.clip(np.asarray(p, dtype=float), _LOGIT_EPSILON, 1 - _LOGIT_EPSILON)
    logit_p = np.log(p_arr / (1 - p_arr))

    def negative_log_likelihood(params: np.ndarray) -> float:
        intercept, slope = params
        z = intercept + slope * logit_p
        # log-sum-exp-stable log(sigmoid(z)) / log(1 - sigmoid(z))
        log_sigmoid = -np.logaddexp(0.0, -z)
        log_one_minus_sigmoid = -np.logaddexp(0.0, z)
        nll = -np.mean(y_arr * log_sigmoid + (1 - y_arr) * log_one_minus_sigmoid)
        return float(nll)

    result = minimize(negative_log_likelihood, x0=np.array([0.0, 1.0]), method="BFGS")
    intercept, slope = result.x
    return float(intercept), float(slope)


def independent_ece(
    y: pd.Series, p: pd.Series, *, n_bins: int, strategy: str = "equal_width"
) -> float:
    y_arr = np.asarray(y, dtype=float)
    p_arr = np.asarray(p, dtype=float)
    if strategy == "equal_width":
        edges = np.linspace(0.0, 1.0, n_bins + 1)
    elif strategy == "equal_mass":
        edges = np.unique(np.quantile(p_arr, np.linspace(0.0, 1.0, n_bins + 1)))
        if len(edges) < 2:
            return 0.0
    else:
        raise ValueError(f"Unknown ECE binning strategy '{strategy}'.")
    edges = edges.copy()
    edges[-1] = edges[-1] + 1e-9
    bin_ids = np.clip(np.digitize(p_arr, edges) - 1, 0, len(edges) - 2)
    total = len(p_arr)
    ece = 0.0
    for b in range(len(edges) - 1):
        mask = bin_ids == b
        if not mask.any():
            continue
        weight = mask.sum() / total
        ece += weight * abs(p_arr[mask].mean() - y_arr[mask].mean())
    return float(ece)


@dataclass(frozen=True)
class BinSensitivityResult:
    strategy: str
    n_bins: int
    ece: float

    def to_dict(self) -> dict[str, Any]:
        return {"strategy": self.strategy, "n_bins": self.n_bins, "ece": round(self.ece, 6)}


def ece_bin_sensitivity(
    y: pd.Series, p: pd.Series, bin_counts: list[int] | None = None
) -> list[BinSensitivityResult]:
    """Recomputes ECE across several bin counts and both binning
    strategies - if the "no calibration needed" conclusion is sensitive
    to this choice, it shows up here as a wide spread of values."""
    bin_counts = bin_counts or [5, 10, 20]
    results = []
    for strategy in ("equal_width", "equal_mass"):
        for n_bins in bin_counts:
            results.append(
                BinSensitivityResult(
                    strategy=strategy,
                    n_bins=n_bins,
                    ece=independent_ece(y, p, n_bins=n_bins, strategy=strategy),
                )
            )
    return results


def recompute_calibration(
    y_test: pd.Series, p_test: pd.Series, original_metrics: dict[str, Any], tolerance: float
) -> list[MetricComparison]:
    original_cal = original_metrics.get("calibration", {})
    intercept, slope = independent_calibration_slope_intercept(y_test, p_test)
    recomputed = {
        "brier_score": independent_brier(y_test, p_test),
        "log_loss": independent_log_loss(y_test, p_test),
        "calibration_intercept": intercept,
        "calibration_slope": slope,
        "expected_calibration_error": independent_ece(
            y_test, p_test, n_bins=10, strategy="equal_width"
        ),
    }
    return [
        compare_metric(name, float(original_cal[name]), value, tolerance)
        for name, value in recomputed.items()
        if name in original_cal
    ]
