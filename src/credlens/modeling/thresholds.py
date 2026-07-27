"""Illustrative operating points (Phase 8 section 15) - NEVER a "optimal
threshold": no false-positive/false-negative cost, revenue, LGD, EAD, or
capital cost exists anywhere in this project to optimize against.

Every threshold is DEFINED on the validation set and only EVALUATED on
the locked test set - `thresholds_for_operating_points` takes both
explicitly and never lets validation-derived numbers leak into the test
evaluation beyond the single threshold value itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve

from credlens.modeling.contracts import EvaluationConfig
from credlens.modeling.evaluation import ConfusionMetrics, confusion_at_threshold

ILLUSTRATIVE_LABEL_EN = "Illustrative review-capacity scenario"
ILLUSTRATIVE_LABEL_PT_BR = "Cenário ilustrativo de capacidade de revisão"


@dataclass(frozen=True)
class OperatingPoint:
    name: str
    point_type: str
    target_value: float
    threshold: float
    test_metrics: ConfusionMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.point_type,
            "target_value": self.target_value,
            "threshold": round(self.threshold, 6),
            "label_en": ILLUSTRATIVE_LABEL_EN,
            "label_pt_br": ILLUSTRATIVE_LABEL_PT_BR,
            **self.test_metrics.to_dict(),
        }


def threshold_for_population_share(p_val: pd.Series, share: float) -> float:
    """The score above which exactly the top `share` fraction of the
    VALIDATION population falls."""
    return float(np.quantile(np.asarray(p_val, dtype=float), 1.0 - share))


def threshold_for_recall(y_val: pd.Series, p_val: pd.Series, target_recall: float) -> float:
    """The highest-scoring threshold on VALIDATION whose recall is
    closest to `target_recall` (approximate by construction - Phase 8
    explicitly calls these "recall aproximado de X%")."""
    _precision, recall, cut_thresholds = precision_recall_curve(y_val, p_val)
    diffs = np.abs(recall[:-1] - target_recall)
    idx = int(np.argmin(diffs))
    return float(cut_thresholds[idx])


def operating_points_from_config(
    y_val: pd.Series,
    p_val: pd.Series,
    y_test: pd.Series,
    p_test: pd.Series,
    config: EvaluationConfig,
) -> list[OperatingPoint]:
    points = []
    for spec in config.thresholds["illustrative_operating_points"]:
        name = spec["name"]
        point_type = spec["type"]
        target_value = float(spec["value"])
        if point_type == "population_share":
            threshold = threshold_for_population_share(p_val, target_value)
        elif point_type == "recall":
            threshold = threshold_for_recall(y_val, p_val, target_value)
        else:
            raise ValueError(f"Unknown operating point type '{point_type}' for '{name}'.")

        test_metrics = confusion_at_threshold(y_test, p_test, threshold)
        points.append(
            OperatingPoint(
                name=name,
                point_type=point_type,
                target_value=target_value,
                threshold=threshold,
                test_metrics=test_metrics,
            )
        )
    return points
