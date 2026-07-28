"""Multicollinearity audit (Phase 9 section 7) over the 18 engineered
behavioral features - correlation matrix, Variance Inflation Factor
(VIF), and the design-matrix condition number, computed on the TRAIN
partition only (the same data the registered logistic regression was fit
on).

VIF is computed with `sklearn.linear_model.LinearRegression` (already a
project dependency, no new one added) - VIF_i = 1 / (1 - R2_i), where
R2_i is the R2 of regressing feature i on every other feature. The
condition number follows the standard collinearity diagnostic
(Belsley/Kuh/Welsch): the ratio of the largest to smallest singular value
of the column-standardized (mean 0, unit norm) feature matrix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression


@dataclass(frozen=True)
class VifRow:
    feature: str
    vif: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "vif": round(self.vif, 4) if np.isfinite(self.vif) else None,
        }


def compute_correlation_matrix(features: pd.DataFrame) -> pd.DataFrame:
    """Operates on whatever columns `features` has - callers pass the
    exact feature set they want audited (the full 18-feature frame, or a
    reduced subset), never a hardcoded column list."""
    return features.corr(method="pearson")


def compute_vif(features: pd.DataFrame) -> list[VifRow]:
    columns = list(features.columns)
    values = features.to_numpy(dtype=float)
    rows = []
    for i, feature in enumerate(columns):
        y = values[:, i]
        x_others = np.delete(values, i, axis=1)
        model = LinearRegression()
        model.fit(x_others, y)
        r2 = model.score(x_others, y)
        vif = float("inf") if r2 >= 1.0 else 1.0 / (1.0 - r2)
        rows.append(VifRow(feature=feature, vif=vif))
    return sorted(rows, key=lambda r: r.vif, reverse=True)


def condition_number(features: pd.DataFrame) -> float:
    """Condition number of the column-standardized design matrix (mean 0,
    unit L2 norm per column) - the standard collinearity diagnostic,
    computed via `numpy.linalg.svd` (independent of, and unrelated to,
    the pipeline's own `StandardScaler`)."""
    values = features.to_numpy(dtype=float)
    centered = values - values.mean(axis=0, keepdims=True)
    norms = np.linalg.norm(centered, axis=0)
    norms[norms == 0] = 1.0
    standardized = centered / norms
    singular_values = np.linalg.svd(standardized, compute_uv=False)
    smallest = singular_values[singular_values > 1e-12]
    if len(smallest) == 0:
        return float("inf")
    return float(singular_values.max() / smallest.min())


@dataclass(frozen=True)
class HighCorrelationPair:
    feature_a: str
    feature_b: str
    correlation: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_a": self.feature_a,
            "feature_b": self.feature_b,
            "correlation": round(self.correlation, 4),
        }


def high_correlation_pairs(corr: pd.DataFrame, threshold: float) -> list[HighCorrelationPair]:
    pairs = []
    columns = list(corr.columns)
    for i, feature_a in enumerate(columns):
        for feature_b in columns[i + 1 :]:
            value = float(np.asarray(corr.loc[feature_a, feature_b]))
            if abs(value) >= threshold:
                pairs.append(HighCorrelationPair(feature_a, feature_b, value))
    return sorted(pairs, key=lambda p: abs(p.correlation), reverse=True)


@dataclass(frozen=True)
class CollinearityReport:
    vif_table: list[VifRow]
    condition_number_value: float
    high_correlation_pairs_list: list[HighCorrelationPair]
    vif_flag_threshold: float
    vif_action_threshold: float
    condition_number_flag_threshold: float
    condition_number_action_threshold: float

    @property
    def features_above_action_threshold(self) -> list[str]:
        return [row.feature for row in self.vif_table if row.vif >= self.vif_action_threshold]

    @property
    def features_above_flag_threshold(self) -> list[str]:
        return [row.feature for row in self.vif_table if row.vif >= self.vif_flag_threshold]

    def to_dict(self) -> dict[str, Any]:
        return {
            "vif_table": [row.to_dict() for row in self.vif_table],
            "condition_number": round(self.condition_number_value, 4),
            "high_correlation_pairs": [p.to_dict() for p in self.high_correlation_pairs_list],
            "vif_flag_threshold": self.vif_flag_threshold,
            "vif_action_threshold": self.vif_action_threshold,
            "condition_number_flag_threshold": self.condition_number_flag_threshold,
            "condition_number_action_threshold": self.condition_number_action_threshold,
            "features_above_action_threshold": self.features_above_action_threshold,
            "features_above_flag_threshold": self.features_above_flag_threshold,
            "condition_number_flagged": self.condition_number_value
            >= self.condition_number_flag_threshold,
            "condition_number_action_needed": (
                self.condition_number_value >= self.condition_number_action_threshold
            ),
        }


def run_collinearity_audit(features: pd.DataFrame, cfg: dict[str, Any]) -> CollinearityReport:
    corr = compute_correlation_matrix(features)
    return CollinearityReport(
        vif_table=compute_vif(features),
        condition_number_value=condition_number(features),
        high_correlation_pairs_list=high_correlation_pairs(
            corr, float(cfg["high_correlation_threshold"])
        ),
        vif_flag_threshold=float(cfg["vif_flag_threshold"]),
        vif_action_threshold=float(cfg["vif_action_threshold"]),
        condition_number_flag_threshold=float(cfg["condition_number_flag_threshold"]),
        condition_number_action_threshold=float(cfg["condition_number_action_threshold"]),
    )


def iteratively_reduce_by_vif(
    features: pd.DataFrame, threshold: float, *, min_features: int = 6
) -> tuple[list[str], list[dict[str, Any]]]:
    """Greedily drops the single highest-VIF feature above `threshold`,
    recomputing VIF on the remaining set each time, until every remaining
    feature is below `threshold` or only `min_features` remain - the
    standard iterative-VIF-elimination procedure for building a reduced,
    less redundant feature set (Phase 9 section 7.3)."""
    remaining = list(features.columns)
    steps: list[dict[str, Any]] = []
    while len(remaining) > min_features:
        vif_table = compute_vif(features[remaining])
        worst = vif_table[0]
        if worst.vif < threshold:
            break
        steps.append({"removed": worst.feature, "vif_at_removal": round(worst.vif, 4)})
        remaining.remove(worst.feature)
    return remaining, steps
