"""Independent spot-check of the Phase 8 robustness/stress-test table
(Phase 9 section 4) - re-implements the two perturbations Phase 8 flagged
as producing the largest degradations
(`out_of_domain_delinquency_code`, `delinquency_worsening`) with fresh
perturbation code and an independent PR-AUC
(`credlens.model_validation.discrimination.independent_pr_auc`), rather
than re-calling `credlens.modeling.robustness.run_robustness_suite`.

Feature engineering itself (`credlens.modeling.features.
engineer_features`) IS reused - it is the fixed, shared transformation
both the original evidence and this validation must apply identically to
be comparable at all (like the frozen predictions elsewhere in this
package), not the evidence being audited. The evidence being audited here
is the DEGRADATION NUMBER, which is computed independently.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from credlens.model_validation.discrimination import (
    MetricComparison,
    compare_metric,
    independent_pr_auc,
)
from credlens.modeling.features import FEATURE_COLUMNS, engineer_features
from credlens.modeling.training import FittedModel, predict_proba_positive

_DELINQUENCY_COLUMNS = ["X6", "X7", "X8", "X9", "X10", "X11"]

SPOT_CHECKED_KINDS = ("delinquency_worsening", "out_of_domain_delinquency_code")


def _independent_delinquency_worsening(raw_test: pd.DataFrame, steps: int) -> pd.DataFrame:
    out = raw_test.copy()
    out[_DELINQUENCY_COLUMNS] = (out[_DELINQUENCY_COLUMNS] + steps).clip(lower=-2, upper=9)
    return engineer_features(out)


def _independent_out_of_domain_code(
    raw_test: pd.DataFrame, code: int, affected_fraction: float, seed: int
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = raw_test.copy()
    mask = rng.random((len(out), len(_DELINQUENCY_COLUMNS))) < affected_fraction
    values = out[_DELINQUENCY_COLUMNS].to_numpy(dtype=float)
    values[mask] = code
    out[_DELINQUENCY_COLUMNS] = values
    return engineer_features(out)


def spot_check_robustness(
    fitted: FittedModel,
    raw_test: pd.DataFrame,
    y_test: pd.Series,
    original_robustness_table: pd.DataFrame,
    *,
    robustness_cfg: dict[str, Any],
    tolerance: float,
    stochastic_tolerance: float,
) -> list[MetricComparison]:
    baseline_features = engineer_features(raw_test)[FEATURE_COLUMNS]
    baseline_p = predict_proba_positive(fitted, baseline_features)
    baseline_pr_auc = independent_pr_auc(y_test, baseline_p)

    comparisons: list[MetricComparison] = []

    worsening_features = _independent_delinquency_worsening(
        raw_test, int(robustness_cfg["delinquency_worsening_steps"])
    )[FEATURE_COLUMNS]
    worsening_p = predict_proba_positive(fitted, worsening_features)
    worsening_degradation = baseline_pr_auc - independent_pr_auc(y_test, worsening_p)
    original_row = original_robustness_table[
        original_robustness_table["kind"] == "delinquency_worsening"
    ]
    if not original_row.empty:
        comparisons.append(
            compare_metric(
                "delinquency_worsening__pr_auc_degradation",
                float(original_row.iloc[0]["pr_auc_degradation"]),
                worsening_degradation,
                tolerance,
            )
        )

    ood_features = _independent_out_of_domain_code(
        raw_test,
        int(robustness_cfg["out_of_domain_delinquency_code"]),
        0.05,
        int(robustness_cfg["seed"]),
    )[FEATURE_COLUMNS]
    ood_p = predict_proba_positive(fitted, ood_features)
    ood_degradation = baseline_pr_auc - independent_pr_auc(y_test, ood_p)
    original_row = original_robustness_table[
        original_robustness_table["kind"] == "out_of_domain_delinquency_code"
    ]
    if not original_row.empty:
        comparisons.append(
            compare_metric(
                "out_of_domain_delinquency_code__pr_auc_degradation",
                float(original_row.iloc[0]["pr_auc_degradation"]),
                ood_degradation,
                stochastic_tolerance,
            )
        )

    return comparisons
