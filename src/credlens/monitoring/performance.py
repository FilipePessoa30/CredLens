"""Performance-drift metrics (Phase 9 section 15.4) - computed only when
a batch's `label_availability` is `"available"`. Reuses
`credlens.model_validation`'s independent metric implementations (not
`credlens.modeling.evaluation`) so the monitoring layer never inherits a
bug from the training-time evidence path either.

When labels are NOT available (the `label_delay` batch), this module is
never called for that batch - the caller marks `labels_pending` instead,
so score drift is never confused with concept/performance drift (section
15.4: "não confunda score drift com concept drift").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from credlens.model_validation.calibration import (
    independent_brier,
    independent_calibration_slope_intercept,
)
from credlens.model_validation.discrimination import (
    independent_ks_statistic,
    independent_pr_auc,
    independent_roc_auc,
)
from credlens.model_validation.thresholds import independent_confusion_counts

LABELS_PENDING = "labels_pending"


@dataclass(frozen=True)
class PerformanceDriftResult:
    n_rows: int
    roc_auc: float
    pr_auc: float
    brier_score: float
    ks_statistic: float
    calibration_intercept: float
    calibration_slope: float
    precision: float
    recall: float
    false_positive_rate: float
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    roc_auc_delta: float
    pr_auc_delta: float
    brier_delta: float
    bootstrap_roc_auc_p2_5: float
    bootstrap_roc_auc_p97_5: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_rows": self.n_rows,
            "roc_auc": round(self.roc_auc, 6),
            "pr_auc": round(self.pr_auc, 6),
            "brier_score": round(self.brier_score, 6),
            "ks_statistic": round(self.ks_statistic, 6),
            "calibration_intercept": round(self.calibration_intercept, 6),
            "calibration_slope": round(self.calibration_slope, 6),
            "precision": round(self.precision, 6),
            "recall": round(self.recall, 6),
            "false_positive_rate": round(self.false_positive_rate, 6),
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "true_negative": self.true_negative,
            "false_negative": self.false_negative,
            "roc_auc_delta": round(self.roc_auc_delta, 6),
            "pr_auc_delta": round(self.pr_auc_delta, 6),
            "brier_delta": round(self.brier_delta, 6),
            "bootstrap_roc_auc_p2_5": round(self.bootstrap_roc_auc_p2_5, 6),
            "bootstrap_roc_auc_p97_5": round(self.bootstrap_roc_auc_p97_5, 6),
        }


def compute_performance_drift(
    y_batch: pd.Series,
    p_batch: pd.Series,
    *,
    threshold: float,
    reference_roc_auc: float,
    reference_pr_auc: float,
    reference_brier: float,
    n_bootstrap: int = 200,
    seed: int = 20260728,
) -> PerformanceDriftResult:
    if y_batch.nunique() < 2:
        raise ValueError("Performance drift needs both classes present in the batch.")

    intercept, slope = independent_calibration_slope_intercept(y_batch, p_batch)
    counts = independent_confusion_counts(y_batch, p_batch, threshold)
    roc_auc = independent_roc_auc(y_batch, p_batch)
    pr_auc = independent_pr_auc(y_batch, p_batch)
    brier = independent_brier(y_batch, p_batch)

    rng = np.random.default_rng(seed)
    y_arr = y_batch.to_numpy()
    p_arr = p_batch.to_numpy()
    positive_idx = np.flatnonzero(y_arr == 1)
    negative_idx = np.flatnonzero(y_arr == 0)
    boot_roc_aucs = []
    for _ in range(n_bootstrap):
        idx = np.concatenate(
            [
                rng.choice(positive_idx, size=len(positive_idx), replace=True),
                rng.choice(negative_idx, size=len(negative_idx), replace=True),
            ]
        )
        try:
            boot_roc_aucs.append(independent_roc_auc(pd.Series(y_arr[idx]), pd.Series(p_arr[idx])))
        except Exception:
            continue

    p2_5 = float(np.percentile(boot_roc_aucs, 2.5)) if boot_roc_aucs else roc_auc
    p97_5 = float(np.percentile(boot_roc_aucs, 97.5)) if boot_roc_aucs else roc_auc

    return PerformanceDriftResult(
        n_rows=len(y_batch),
        roc_auc=roc_auc,
        pr_auc=pr_auc,
        brier_score=brier,
        ks_statistic=independent_ks_statistic(y_batch, p_batch),
        calibration_intercept=intercept,
        calibration_slope=slope,
        precision=counts.precision,
        recall=counts.recall,
        false_positive_rate=1.0 - counts.specificity,
        true_positive=counts.true_positive,
        false_positive=counts.false_positive,
        true_negative=counts.true_negative,
        false_negative=counts.false_negative,
        roc_auc_delta=roc_auc - reference_roc_auc,
        pr_auc_delta=pr_auc - reference_pr_auc,
        brier_delta=brier - reference_brier,
        bootstrap_roc_auc_p2_5=p2_5,
        bootstrap_roc_auc_p97_5=p97_5,
    )
