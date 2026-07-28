"""Independent recomputation of the multi-seed split-stability summary
(Phase 9 section 4) - re-derives mean/stdev directly from the per-seed
rows Phase 8 already wrote (`<experiment_id>__split_stability.csv`) with
a plain `numpy` reduction, rather than trusting the aggregate
`Experiment.metrics["split_stability"]` dict Phase 8's own code computed
and stored. Does NOT refit any model - every per-seed ROC-AUC/PR-AUC
value here is the one Phase 8 already measured; only the aggregation
(mean, sample stdev) is redone independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from credlens.model_validation.discrimination import MetricComparison, compare_metric


@dataclass(frozen=True)
class StabilityRecomputation:
    n_seeds: int
    roc_auc_mean: float
    roc_auc_stdev: float
    pr_auc_mean: float
    pr_auc_stdev: float
    comparisons: list[MetricComparison]

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_seeds": self.n_seeds,
            "roc_auc_mean": round(self.roc_auc_mean, 6),
            "roc_auc_stdev": round(self.roc_auc_stdev, 6),
            "pr_auc_mean": round(self.pr_auc_mean, 6),
            "pr_auc_stdev": round(self.pr_auc_stdev, 6),
            "comparisons": [c.to_dict() for c in self.comparisons],
        }


def recompute_split_stability(
    split_stability_table: pd.DataFrame, original_summary: dict[str, Any], tolerance: float
) -> StabilityRecomputation:
    roc_aucs = split_stability_table["roc_auc"].to_numpy(dtype=float)
    pr_aucs = split_stability_table["pr_auc"].to_numpy(dtype=float)
    if len(roc_aucs) < 2:
        raise ValueError("Split-stability recomputation needs at least 2 seeds.")

    roc_auc_mean = float(roc_aucs.mean())
    roc_auc_stdev = float(roc_aucs.std(ddof=1))
    pr_auc_mean = float(pr_aucs.mean())
    pr_auc_stdev = float(pr_aucs.std(ddof=1))

    comparisons = [
        compare_metric(
            "roc_auc_mean", float(original_summary["roc_auc_mean"]), roc_auc_mean, tolerance
        ),
        compare_metric(
            "roc_auc_stdev", float(original_summary["roc_auc_stdev"]), roc_auc_stdev, tolerance
        ),
        compare_metric(
            "pr_auc_mean", float(original_summary["pr_auc_mean"]), pr_auc_mean, tolerance
        ),
        compare_metric(
            "pr_auc_stdev", float(original_summary["pr_auc_stdev"]), pr_auc_stdev, tolerance
        ),
    ]
    return StabilityRecomputation(
        n_seeds=len(roc_aucs),
        roc_auc_mean=roc_auc_mean,
        roc_auc_stdev=roc_auc_stdev,
        pr_auc_mean=pr_auc_mean,
        pr_auc_stdev=pr_auc_stdev,
        comparisons=comparisons,
    )
