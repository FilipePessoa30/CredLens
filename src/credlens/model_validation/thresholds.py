"""Independent re-derivation of the illustrative operating points (Phase 9
section 11) - confusion counts via plain boolean-mask sums (not
`credlens.modeling.evaluation.confusion_at_threshold`), population-share
thresholds via direct `numpy.sort` indexing (not
`credlens.modeling.thresholds.threshold_for_population_share`), and
recall-target thresholds via a manual precision-recall sweep (not
`sklearn.metrics.precision_recall_curve`).

Also proves the two properties Phase 9 section 11 asks to be tested
directly: determinism (recomputing the same threshold twice from the
same validation scores gives the identical value) and small-perturbation
sensitivity (a small resample of the validation set moves the operating
threshold only slightly, never wildly) - both exercised as plain
functions here, asserted on in `tests/test_model_validation_thresholds.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from credlens.model_validation.discrimination import MetricComparison, compare_metric


@dataclass(frozen=True)
class IndependentConfusionCounts:
    threshold: float
    n_total: int
    n_flagged: int
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    precision: float
    recall: float
    specificity: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "threshold": round(self.threshold, 6),
            "n_total": self.n_total,
            "n_flagged": self.n_flagged,
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "true_negative": self.true_negative,
            "false_negative": self.false_negative,
            "precision": round(self.precision, 6),
            "recall": round(self.recall, 6),
            "specificity": round(self.specificity, 6),
        }


def independent_confusion_counts(
    y: pd.Series, p: pd.Series, threshold: float
) -> IndependentConfusionCounts:
    y_arr = np.asarray(y, dtype=int)
    flagged = np.asarray(p, dtype=float) >= threshold
    actual_positive = y_arr == 1
    actual_negative = y_arr == 0

    tp = int(np.sum(flagged & actual_positive))
    fp = int(np.sum(flagged & actual_negative))
    tn = int(np.sum(~flagged & actual_negative))
    fn = int(np.sum(~flagged & actual_positive))

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0

    return IndependentConfusionCounts(
        threshold=threshold,
        n_total=len(y_arr),
        n_flagged=int(flagged.sum()),
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        precision=precision,
        recall=recall,
        specificity=specificity,
    )


def independent_threshold_for_population_share(p_val: pd.Series, share: float) -> float:
    """Sorts validation scores descending and returns the score at
    position `round(share * n) - 1` - a direct index lookup, not
    `numpy.quantile`'s interpolation-based algorithm."""
    sorted_desc = np.sort(np.asarray(p_val, dtype=float))[::-1]
    n = len(sorted_desc)
    cut_index = max(0, min(n - 1, round(share * n) - 1))
    return float(sorted_desc[cut_index])


def independent_threshold_for_recall(
    y_val: pd.Series, p_val: pd.Series, target_recall: float
) -> float:
    """Sweeps every distinct observed score as a candidate threshold
    (descending), accumulates true positives, and returns the threshold
    whose recall is closest to `target_recall` - a manual sweep, not
    `sklearn.metrics.precision_recall_curve`."""
    y_arr = np.asarray(y_val, dtype=int)
    p_arr = np.asarray(p_val, dtype=float)
    n_pos = int((y_arr == 1).sum())
    if n_pos == 0:
        raise ValueError("Cannot compute a recall-based threshold with zero positives.")

    candidate_thresholds = np.unique(p_arr)[::-1]
    best_threshold = candidate_thresholds[0]
    best_diff = float("inf")
    for threshold in candidate_thresholds:
        flagged = p_arr >= threshold
        tp = int(np.sum(flagged & (y_arr == 1)))
        recall = tp / n_pos
        diff = abs(recall - target_recall)
        if diff < best_diff:
            best_diff = diff
            best_threshold = threshold
    return float(best_threshold)


def population_share_threshold_stability(
    p_val: pd.Series,
    share: float,
    *,
    n_trials: int = 5,
    subsample_frac: float = 0.9,
    seed: int = 20260728,
) -> list[float]:
    """Recomputes the population-share threshold on `n_trials`
    subsamples of the validation scores - demonstrates the threshold
    moves only slightly under small prevalence/composition perturbation,
    never wildly (Phase 9 section 11: "pequenas variações de
    prevalência")."""
    rng = np.random.default_rng(seed)
    p_arr = np.asarray(p_val, dtype=float)
    n_sub = max(1, round(len(p_arr) * subsample_frac))
    thresholds = []
    for _ in range(n_trials):
        idx = rng.choice(len(p_arr), size=n_sub, replace=False)
        thresholds.append(independent_threshold_for_population_share(pd.Series(p_arr[idx]), share))
    return thresholds


def recompute_operating_points(
    thresholds_table: pd.DataFrame,
    y_val: pd.Series,
    p_val: pd.Series,
    y_test: pd.Series,
    p_test: pd.Series,
    tolerance: float,
) -> list[MetricComparison]:
    """For every row in the original `thresholds` table, independently
    re-derives the threshold from validation scores and the confusion
    counts from test scores, comparing both against the original."""
    comparisons: list[MetricComparison] = []
    for _, row in thresholds_table.iterrows():
        name = row["name"]
        point_type = row["type"]
        target_value = float(row["target_value"])
        if point_type == "population_share":
            recomputed_threshold = independent_threshold_for_population_share(p_val, target_value)
        elif point_type == "recall":
            recomputed_threshold = independent_threshold_for_recall(y_val, p_val, target_value)
        else:
            continue
        comparisons.append(
            compare_metric(
                f"{name}__threshold", float(row["threshold"]), recomputed_threshold, tolerance
            )
        )
        recomputed_counts = independent_confusion_counts(y_test, p_test, recomputed_threshold)
        comparisons.append(
            compare_metric(
                f"{name}__recall", float(row["recall"]), recomputed_counts.recall, tolerance
            )
        )
        comparisons.append(
            compare_metric(
                f"{name}__precision",
                float(row["precision"]),
                recomputed_counts.precision,
                tolerance,
            )
        )
    return comparisons
