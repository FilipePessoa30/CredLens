"""Independent re-derivation of discrimination metrics (Phase 9 section 4:
"não chame a mesma função usada originalmente para calcular a evidência,
quando uma implementação independente for viável").

`credlens.modeling.evaluation` computes ROC-AUC via `sklearn.metrics.
roc_auc_score` (trapezoidal integration of the ROC curve) and PR-AUC via
`sklearn.metrics.average_precision_score`. This module re-derives the
SAME mathematical quantities with different algorithms - a rank-sum
(Mann-Whitney U) estimator for ROC-AUC, a manual step-function
accumulation for average precision, and an empirical-CDF maximum
separation for KS - so a bug or misconfiguration in the original
computation would not be silently reproduced here too.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


class DiscriminationValidationError(Exception):
    """Raised when independently recomputed discrimination metrics
    diverge from the original evidence by more than the configured
    tolerance."""


def independent_roc_auc(y: pd.Series, p: pd.Series) -> float:
    """Rank-sum (Mann-Whitney U) estimator: AUC = U / (n_pos * n_neg),
    where U is the sum of positive-class ranks minus the minimum possible
    sum. Ties are handled via average ranking (`scipy.stats.rankdata`'s
    'average' method, applied here directly via `pandas.Series.rank`)."""
    y_arr = np.asarray(y, dtype=int)
    p_arr = np.asarray(p, dtype=float)
    n_pos = int((y_arr == 1).sum())
    n_neg = int((y_arr == 0).sum())
    if n_pos == 0 or n_neg == 0:
        raise DiscriminationValidationError("ROC-AUC is undefined with only one class present.")
    ranks = pd.Series(p_arr).rank(method="average").to_numpy()
    rank_sum_positive = ranks[y_arr == 1].sum()
    u_statistic = rank_sum_positive - n_pos * (n_pos + 1) / 2.0
    return float(u_statistic / (n_pos * n_neg))


def independent_pr_auc(y: pd.Series, p: pd.Series) -> float:
    """Average precision via the same step-function definition
    `sklearn.metrics.average_precision_score` uses (AP = sum_k (R_k -
    R_{k-1}) * P_k, sorted by descending score), accumulated here with a
    plain cumulative-sum pass rather than calling that function."""
    y_arr = np.asarray(y, dtype=int)
    p_arr = np.asarray(p, dtype=float)
    n_pos = int((y_arr == 1).sum())
    if n_pos == 0:
        raise DiscriminationValidationError("PR-AUC is undefined with no positive examples.")
    order = np.argsort(-p_arr, kind="mergesort")
    y_sorted = y_arr[order]
    cum_tp = np.cumsum(y_sorted)
    n_flagged = np.arange(1, len(y_sorted) + 1)
    precision = cum_tp / n_flagged
    recall = cum_tp / n_pos
    recall_prev = np.concatenate(([0.0], recall[:-1]))
    delta_recall = recall - recall_prev
    return float(np.sum(delta_recall * precision))


def independent_ks_statistic(y: pd.Series, p: pd.Series) -> float:
    """Maximum separation between the empirical CDFs of predicted score
    for the positive and negative classes, evaluated at every observed
    score value - computed via `numpy.searchsorted` against each class's
    own sorted scores, never through `sklearn.metrics.roc_curve`."""
    y_arr = np.asarray(y, dtype=int)
    p_arr = np.asarray(p, dtype=float)
    positive_scores = np.sort(p_arr[y_arr == 1])
    negative_scores = np.sort(p_arr[y_arr == 0])
    if len(positive_scores) == 0 or len(negative_scores) == 0:
        raise DiscriminationValidationError("KS statistic is undefined with only one class.")
    grid = np.unique(p_arr)
    cdf_pos = np.searchsorted(positive_scores, grid, side="right") / len(positive_scores)
    cdf_neg = np.searchsorted(negative_scores, grid, side="right") / len(negative_scores)
    return float(np.max(np.abs(cdf_pos - cdf_neg)))


@dataclass(frozen=True)
class MetricComparison:
    metric: str
    original_value: float
    recomputed_value: float
    absolute_difference: float
    tolerance: float
    within_tolerance: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "original_value": round(self.original_value, 6),
            "recomputed_value": round(self.recomputed_value, 6),
            "absolute_difference": round(self.absolute_difference, 8),
            "tolerance": self.tolerance,
            "within_tolerance": self.within_tolerance,
        }


def compare_metric(
    metric: str, original: float, recomputed: float, tolerance: float
) -> MetricComparison:
    diff = abs(original - recomputed)
    return MetricComparison(
        metric=metric,
        original_value=original,
        recomputed_value=recomputed,
        absolute_difference=diff,
        tolerance=tolerance,
        within_tolerance=diff <= tolerance,
    )


def recompute_discrimination(
    y_test: pd.Series, p_test: pd.Series, original_metrics: dict[str, Any], tolerance: float
) -> list[MetricComparison]:
    """Recomputes ROC-AUC/PR-AUC/KS independently and compares each
    against the FROZEN original evidence (never against a live re-read of
    `reports/modeling/`)."""
    original_disc = original_metrics.get("discrimination", {})
    recomputed = {
        "roc_auc": independent_roc_auc(y_test, p_test),
        "pr_auc": independent_pr_auc(y_test, p_test),
        "ks_statistic": independent_ks_statistic(y_test, p_test),
    }
    return [
        compare_metric(name, float(original_disc[name]), value, tolerance)
        for name, value in recomputed.items()
        if name in original_disc
    ]
