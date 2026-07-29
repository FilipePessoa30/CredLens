"""Full metrics suite (Phase 8 section 13) - deliberately grouped by KIND
(discrimination vs. calibration vs. threshold-dependent vs. ranking) so no
report can accidentally present "accuracy" alone as proof of quality
(section 13: "Não declare accuracy isoladamente como prova de qualidade").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)

_LOGIT_EPSILON = 1e-6
_N_DECILES = 10
_N_CALIBRATION_BINS = 10


@dataclass(frozen=True)
class ConfusionMetrics:
    threshold: float
    n_flagged: int
    n_total: int
    true_positive: int
    true_negative: int
    false_positive: int
    false_negative: int
    precision: float
    recall: float
    specificity: float
    f1: float
    balanced_accuracy: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "threshold": round(self.threshold, 6),
            "n_flagged": self.n_flagged,
            "n_total": self.n_total,
            "true_positive": self.true_positive,
            "true_negative": self.true_negative,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "precision": round(self.precision, 6),
            "recall": round(self.recall, 6),
            "specificity": round(self.specificity, 6),
            "f1": round(self.f1, 6),
            "balanced_accuracy": round(self.balanced_accuracy, 6),
        }


def prevalence(y: pd.Series | np.ndarray) -> float:
    return float(np.mean(np.asarray(y, dtype=float)))


def roc_auc(y: pd.Series, p: pd.Series) -> float:
    return float(roc_auc_score(y, p))


def pr_auc(y: pd.Series, p: pd.Series) -> float:
    return float(average_precision_score(y, p))


def brier(y: pd.Series, p: pd.Series) -> float:
    return float(brier_score_loss(y, p))


def logloss(y: pd.Series, p: pd.Series) -> float:
    p_clipped = np.clip(np.asarray(p, dtype=float), _LOGIT_EPSILON, 1 - _LOGIT_EPSILON)
    return float(log_loss(y, p_clipped, labels=[0, 1]))


def ks_statistic(y: pd.Series, p: pd.Series) -> float:
    """Kolmogorov-Smirnov statistic: the maximum separation between the
    cumulative distributions of predicted risk for the positive and
    negative classes along the ROC curve."""
    fpr, tpr, _ = roc_curve(y, p)
    return float(np.max(np.abs(tpr - fpr)))


def calibration_intercept_slope(y: pd.Series, p: pd.Series) -> tuple[float, float]:
    """Fits `y ~ logit(p)` via unregularized logistic regression - the
    standard "calibration in the large/small" diagnostic. Slope 1.0 and
    intercept 0.0 is perfect calibration; slope < 1 means predictions are
    too extreme, intercept != 0 means predictions are systematically
    biased high/low."""
    p_clipped = np.clip(np.asarray(p, dtype=float), _LOGIT_EPSILON, 1 - _LOGIT_EPSILON)
    logit_p = np.log(p_clipped / (1 - p_clipped)).reshape(-1, 1)
    # C=np.inf is the current, non-deprecated way to request an
    # unregularized fit (the old `penalty=None` spelling now warns).
    model = LogisticRegression(C=np.inf, solver="lbfgs")
    model.fit(logit_p, y)
    return float(model.intercept_[0]), float(model.coef_[0][0])


def expected_calibration_error(
    y: pd.Series, p: pd.Series, n_bins: int = _N_CALIBRATION_BINS
) -> float:
    """Mean absolute gap between predicted and observed event rate,
    weighted by bin size, across `n_bins` equal-width probability bins."""
    y_arr = np.asarray(y, dtype=float)
    p_arr = np.asarray(p, dtype=float)
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_edges[-1] = 1.0 + 1e-9
    bin_ids = np.digitize(p_arr, bin_edges) - 1
    bin_ids = np.clip(bin_ids, 0, n_bins - 1)
    total = len(p_arr)
    ece = 0.0
    for b in range(n_bins):
        mask = bin_ids == b
        if not mask.any():
            continue
        weight = mask.sum() / total
        ece += weight * abs(p_arr[mask].mean() - y_arr[mask].mean())
    return float(ece)


def confusion_at_threshold(y: pd.Series, p: pd.Series, threshold: float) -> ConfusionMetrics:
    """`labels=[0, 1]` is passed explicitly to every sklearn metric that
    accepts it, so a single-class group (a tiny subgroup slice, or a
    perturbed batch) never triggers sklearn's "A single label was found"
    UserWarning by letting it infer labels from the data. `balanced_
    accuracy_score` accepts no `labels` parameter at all, so it is never
    called here - balanced accuracy is instead its own textbook
    definition, the average of recall (sensitivity) and specificity,
    computed directly from the already-guarded values below (both are
    well-defined, via explicit zero-division handling, even when one
    class is entirely absent)."""
    flagged = (np.asarray(p, dtype=float) >= threshold).astype(int)
    y_arr = np.asarray(y, dtype=int)
    tn, fp, fn, tp = confusion_matrix(y_arr, flagged, labels=[0, 1]).ravel()
    precision = float(precision_score(y_arr, flagged, labels=[0, 1], zero_division=0.0))
    recall = float(recall_score(y_arr, flagged, labels=[0, 1], zero_division=0.0))
    specificity = float(tn / (tn + fp)) if (tn + fp) > 0 else 0.0
    f1 = float(f1_score(y_arr, flagged, labels=[0, 1], zero_division=0.0))
    balanced_acc = (recall + specificity) / 2.0
    return ConfusionMetrics(
        threshold=threshold,
        n_flagged=int(flagged.sum()),
        n_total=len(y_arr),
        true_positive=int(tp),
        true_negative=int(tn),
        false_positive=int(fp),
        false_negative=int(fn),
        precision=precision,
        recall=recall,
        specificity=specificity,
        f1=f1,
        balanced_accuracy=balanced_acc,
    )


def decile_table(y: pd.Series, p: pd.Series, n_deciles: int = _N_DECILES) -> pd.DataFrame:
    """Deciles ranked from HIGHEST predicted risk (decile 1) to lowest
    (decile `n_deciles`) - lift, cumulative gains, and per-decile event
    rate/capture rate, the standard "risk ranking" diagnostics (Phase 8
    section 13)."""
    frame = pd.DataFrame({"y": np.asarray(y, dtype=int), "p": np.asarray(p, dtype=float)})
    frame = frame.sort_values("p", ascending=False).reset_index(drop=True)
    frame["decile"] = (np.arange(len(frame)) * n_deciles // len(frame)) + 1
    overall_rate = frame["y"].mean()
    total_positives = frame["y"].sum()

    rows = []
    cumulative_positives = 0
    cumulative_n = 0
    for decile in range(1, n_deciles + 1):
        bucket = frame[frame["decile"] == decile]
        n = len(bucket)
        positives = int(bucket["y"].sum())
        cumulative_positives += positives
        cumulative_n += n
        event_rate = positives / n if n > 0 else 0.0
        rows.append(
            {
                "decile": decile,
                "n": n,
                "n_positive": positives,
                "event_rate": round(event_rate, 6),
                "lift": round(event_rate / overall_rate, 6) if overall_rate > 0 else 0.0,
                "capture_rate": (
                    round(positives / total_positives, 6) if total_positives > 0 else 0.0
                ),
                "cumulative_capture_rate": (
                    round(cumulative_positives / total_positives, 6) if total_positives > 0 else 0.0
                ),
                "cumulative_population_share": round(cumulative_n / len(frame), 6),
            }
        )
    return pd.DataFrame(rows)


def full_metrics(y: pd.Series, p: pd.Series, *, threshold: float = 0.5) -> dict[str, Any]:
    """Every metric Phase 8 section 13 requires, grouped by kind so a
    reader can tell threshold-independent discrimination/ranking apart
    from a threshold-dependent snapshot."""
    intercept, slope = calibration_intercept_slope(y, p)
    confusion = confusion_at_threshold(y, p, threshold)
    return {
        "prevalence": round(prevalence(y), 6),
        "discrimination": {
            "roc_auc": round(roc_auc(y, p), 6),
            "pr_auc": round(pr_auc(y, p), 6),
            "ks_statistic": round(ks_statistic(y, p), 6),
        },
        "calibration": {
            "brier_score": round(brier(y, p), 6),
            "log_loss": round(logloss(y, p), 6),
            "calibration_intercept": round(intercept, 6),
            "calibration_slope": round(slope, 6),
            "expected_calibration_error": round(expected_calibration_error(y, p), 6),
        },
        "threshold_dependent": {"threshold": threshold, **confusion.to_dict()},
        "ranking": {"decile_table": decile_table(y, p).to_dict(orient="records")},
    }
