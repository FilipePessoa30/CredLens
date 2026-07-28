"""Orchestrates independent recomputation (Phase 9 sections 4, 11) against
the FROZEN evidence manifest - never a live re-read of `reports/
modeling/` beyond the exact tables the evidence manifest already hashed.

Divergence beyond the configured tolerance is a hard failure here, not a
warning - `credlens.model_validation.decision`'s
`independent_metrics_reproduced` gate reads this report's `all_passed`
field directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from credlens.model_validation.calibration import recompute_calibration
from credlens.model_validation.discrimination import MetricComparison, recompute_discrimination
from credlens.model_validation.evidence import EvidenceManifest
from credlens.model_validation.stability import StabilityRecomputation, recompute_split_stability
from credlens.model_validation.thresholds import recompute_operating_points
from credlens.modeling.registry import RegistryError, load_experiment

TABLES_DIR = Path("reports/modeling/tables")
EXPERIMENTS_DIR = Path("reports/modeling/experiments")

MAIN_MODEL_KIND = "logistic_regression"


class RecomputationError(Exception):
    """Raised when a required frozen artifact is missing."""


@dataclass(frozen=True)
class RecomputationReport:
    experiment_id: str
    discrimination_comparisons: list[MetricComparison]
    calibration_comparisons: list[MetricComparison]
    operating_point_comparisons: list[MetricComparison]
    stability: StabilityRecomputation
    all_passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "discrimination_comparisons": [c.to_dict() for c in self.discrimination_comparisons],
            "calibration_comparisons": [c.to_dict() for c in self.calibration_comparisons],
            "operating_point_comparisons": [c.to_dict() for c in self.operating_point_comparisons],
            "stability": self.stability.to_dict(),
            "all_passed": self.all_passed,
        }


def run_recomputation(
    evidence: EvidenceManifest,
    tolerance: float,
    *,
    operating_point_tolerance: float | None = None,
    repo_root: Path | None = None,
) -> RecomputationReport:
    repo_root = repo_root or Path.cwd()
    experiment_id = evidence.experiment_id
    try:
        experiment = load_experiment(repo_root / EXPERIMENTS_DIR / f"{experiment_id}.json")
    except RegistryError as exc:
        raise RecomputationError(str(exc)) from exc

    predictions_val_path = repo_root / TABLES_DIR / f"{experiment_id}__predictions_val.csv"
    predictions_test_path = repo_root / TABLES_DIR / f"{experiment_id}__predictions_test.csv"
    thresholds_path = repo_root / TABLES_DIR / f"{experiment_id}__thresholds.csv"
    stability_path = repo_root / TABLES_DIR / f"{experiment_id}__split_stability.csv"
    for path in (predictions_val_path, predictions_test_path, thresholds_path, stability_path):
        if not path.is_file():
            raise RecomputationError(f"Required frozen artifact missing at '{path}'.")

    predictions_val = pd.read_csv(predictions_val_path)
    predictions_test = pd.read_csv(predictions_test_path)
    thresholds_table = pd.read_csv(thresholds_path)
    stability_table = pd.read_csv(stability_path)

    y_val, p_val = predictions_val["y_true"], predictions_val[MAIN_MODEL_KIND]
    y_test, p_test = predictions_test["y_true"], predictions_test[MAIN_MODEL_KIND]

    original_test_metrics = evidence.original_test_metrics
    discrimination_comparisons = recompute_discrimination(
        y_test, p_test, original_test_metrics, tolerance
    )
    calibration_comparisons = recompute_calibration(
        y_test, p_test, original_test_metrics, tolerance
    )
    operating_point_comparisons = recompute_operating_points(
        thresholds_table,
        y_val,
        p_val,
        y_test,
        p_test,
        operating_point_tolerance if operating_point_tolerance is not None else tolerance,
    )
    stability = recompute_split_stability(
        stability_table, experiment.metrics["split_stability"], tolerance
    )

    all_passed = (
        all(c.within_tolerance for c in discrimination_comparisons)
        and all(c.within_tolerance for c in calibration_comparisons)
        and all(c.within_tolerance for c in operating_point_comparisons)
        and all(c.within_tolerance for c in stability.comparisons)
    )
    return RecomputationReport(
        experiment_id=experiment_id,
        discrimination_comparisons=discrimination_comparisons,
        calibration_comparisons=calibration_comparisons,
        operating_point_comparisons=operating_point_comparisons,
        stability=stability,
        all_passed=all_passed,
    )
