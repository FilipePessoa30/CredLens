"""Calibrates alert thresholds FROM the reference's own bootstrap
resampling (Phase 9 section 16) - never a copied market-generic PSI/KS
band. For each metric family, `n_resamples` batch-sized subsamples are
drawn from the reference population itself (which by construction has
ZERO real drift versus the full reference) and the SAME drift/
performance metric is computed against the full reference every time,
building an empirical null distribution. The configured percentiles
(`review_percentile`, `material_deviation_percentile`) of that null
distribution become this reference's calibrated thresholds - a
different number for every reference, on purpose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from credlens.model_validation.calibration import independent_brier
from credlens.model_validation.discrimination import independent_pr_auc, independent_roc_auc
from credlens.monitoring.drift import population_stability_index


class ThresholdsError(Exception):
    """Raised when calibrated thresholds cannot be found or loaded."""


THRESHOLDS_STATE_ORDER = (
    "insufficient_sample",
    "within_reference_variability",
    "review",
    "material_deviation",
    "blocked_input",
)


@dataclass(frozen=True)
class CalibratedThreshold:
    metric: str
    review_cutoff: float
    material_deviation_cutoff: float
    n_resamples: int
    batch_size: int
    min_sample_size_for_alert: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "review_cutoff": round(self.review_cutoff, 6),
            "material_deviation_cutoff": round(self.material_deviation_cutoff, 6),
            "n_resamples": self.n_resamples,
            "batch_size": self.batch_size,
            "min_sample_size_for_alert": self.min_sample_size_for_alert,
        }


def classify_state(
    observed_absolute_value: float, calibrated: CalibratedThreshold, n_sample: int
) -> str:
    """Phase 10 gate F/batch-size-study: a sample too small to trust this
    metric's estimate is explicitly distinguished from a metric that WAS
    reliably checked and found within normal variability - never
    conflated into the same "nothing to see here" status, and never
    escalated to a high alert (`credlens.monitoring.alerts.build_alert`
    treats both `insufficient_sample` and `within_reference_variability`
    identically: no Alert record)."""
    if n_sample < calibrated.min_sample_size_for_alert:
        return "insufficient_sample"
    if observed_absolute_value >= calibrated.material_deviation_cutoff:
        return "material_deviation"
    if observed_absolute_value >= calibrated.review_cutoff:
        return "review"
    return "within_reference_variability"


def calibrate_thresholds(
    reference_population: pd.DataFrame,
    reference_feature_stats: dict[str, Any],
    thresholds_config: Any,
    *,
    batch_size: int,
    feature_columns: list[str],
    n_resamples: int = 100,
    seed: int = 20260728,
) -> dict[str, CalibratedThreshold]:
    calib = thresholds_config.calibration
    review_pct = float(calib["review_percentile"])
    material_pct = float(calib["material_deviation_percentile"])
    min_n = int(calib["min_sample_size_for_alert"])
    rng = np.random.default_rng(seed)
    n = len(reference_population)

    psi_null: list[float] = []
    for _ in range(n_resamples):
        feature = feature_columns[rng.integers(0, len(feature_columns))]
        idx = rng.choice(n, size=min(batch_size, n), replace=False)
        subsample = reference_population[feature].to_numpy(dtype=float)[idx]
        full = reference_population[feature].to_numpy(dtype=float)
        bin_edges = reference_feature_stats[feature]["histogram"]["bin_edges"]
        psi_null.append(abs(population_stability_index(full, subsample, bin_edges)))

    score_shift_null: list[float] = []
    for _ in range(n_resamples):
        idx = rng.choice(n, size=min(batch_size, n), replace=False)
        subsample_scores = reference_population["score"].to_numpy(dtype=float)[idx]
        score_shift_null.append(
            abs(float(subsample_scores.mean()) - float(reference_population["score"].mean()))
        )

    perf_null: dict[str, list[float]] = {"roc_auc_delta": [], "pr_auc_delta": [], "brier_delta": []}
    y_full = reference_population["y_true"].to_numpy()
    p_full = reference_population["score"].to_numpy()
    reference_roc_auc = independent_roc_auc(pd.Series(y_full), pd.Series(p_full))
    reference_pr_auc = independent_pr_auc(pd.Series(y_full), pd.Series(p_full))
    reference_brier = independent_brier(pd.Series(y_full), pd.Series(p_full))
    for _ in range(n_resamples):
        idx = rng.choice(n, size=min(batch_size, n), replace=False)
        y_s, p_s = y_full[idx], p_full[idx]
        if len(set(y_s.tolist())) < 2:
            continue
        perf_null["roc_auc_delta"].append(
            abs(independent_roc_auc(pd.Series(y_s), pd.Series(p_s)) - reference_roc_auc)
        )
        perf_null["pr_auc_delta"].append(
            abs(independent_pr_auc(pd.Series(y_s), pd.Series(p_s)) - reference_pr_auc)
        )
        perf_null["brier_delta"].append(
            abs(independent_brier(pd.Series(y_s), pd.Series(p_s)) - reference_brier)
        )

    def _cutoffs(name: str, null: list[float]) -> CalibratedThreshold:
        arr = np.array(null) if null else np.array([0.0])
        return CalibratedThreshold(
            metric=name,
            review_cutoff=float(np.percentile(arr, review_pct)),
            material_deviation_cutoff=float(np.percentile(arr, material_pct)),
            n_resamples=len(null),
            batch_size=batch_size,
            min_sample_size_for_alert=min_n,
        )

    result = {
        "psi": _cutoffs("psi", psi_null),
        "score_mean_shift": _cutoffs("score_mean_shift", score_shift_null),
        "roc_auc_delta": _cutoffs("roc_auc_delta", perf_null["roc_auc_delta"]),
        "pr_auc_delta": _cutoffs("pr_auc_delta", perf_null["pr_auc_delta"]),
        "brier_delta": _cutoffs("brier_delta", perf_null["brier_delta"]),
    }
    return result


def data_quality_fixed_cutoffs(
    thresholds_config: Any, *, batch_size: int
) -> dict[str, CalibratedThreshold]:
    """Phase 10B (Release Candidate Acceptance Remediation) - `data_
    quality`'s 4 metrics (missingness/domain/range/duplicate rate) cannot
    be bootstrap-calibrated the way `calibrate_thresholds` calibrates
    psi/score/performance: the reference population is the real,
    already-audited UCI benchmark, which has ZERO such violations by
    construction, so every bootstrap resample of that null is also
    exactly zero - a percentile of an all-zero array is meaningless and
    would make `classify_state`'s `>=` comparison misfire on a genuinely
    clean batch. Fixed, explicitly documented cutoffs are used instead -
    see `config/monitoring/thresholds.yml`'s `data_quality_fixed_
    thresholds` comment for the full rationale."""
    dq_cfg = thresholds_config.data_quality_fixed_thresholds
    review = float(dq_cfg["review_rate_threshold"])
    material = float(dq_cfg["material_rate_threshold"])
    min_n = int(thresholds_config.calibration["min_sample_size_for_alert"])
    metrics = list(thresholds_config.metric_families["data_quality"]["metrics"])
    return {
        metric: CalibratedThreshold(
            metric=metric,
            review_cutoff=review,
            material_deviation_cutoff=material,
            n_resamples=0,
            batch_size=batch_size,
            min_sample_size_for_alert=min_n,
        )
        for metric in metrics
    }


def calibrate_target_distribution_drift(
    reference_population: pd.DataFrame,
    thresholds_config: Any,
    *,
    batch_size: int,
    seed: int,
) -> CalibratedThreshold:
    """Bootstrap-calibrated (genuine non-degenerate null: real historical
    sampling variance in event rate, unlike `data_quality_fixed_cutoffs`
    above) - a DIRECT target-prevalence check, separate from `score_
    drift`'s indirect score-distribution proxy (Phase 10B: labels are
    available in this offline simulation, so prevalence can be checked
    directly instead of only inferred from the score)."""
    cfg = thresholds_config.target_distribution_drift_calibration
    n_resamples = int(cfg["n_resamples"])
    rng = np.random.default_rng(seed)
    y_full = reference_population["y_true"].to_numpy(dtype=float)
    n = len(y_full)
    reference_rate = float(y_full.mean())
    null: list[float] = []
    for _ in range(n_resamples):
        idx = rng.choice(n, size=min(batch_size, n), replace=False)
        null.append(abs(float(y_full[idx].mean()) - reference_rate))
    arr = np.array(null) if null else np.array([0.0])
    return CalibratedThreshold(
        metric="event_rate_delta",
        review_cutoff=float(np.percentile(arr, float(cfg["review_percentile"]))),
        material_deviation_cutoff=float(
            np.percentile(arr, float(cfg["material_deviation_percentile"]))
        ),
        n_resamples=len(null),
        batch_size=batch_size,
        min_sample_size_for_alert=int(thresholds_config.calibration["min_sample_size_for_alert"]),
    )


def calibrate_subgroup_composition_drift(
    reference_population: pd.DataFrame,
    thresholds_config: Any,
    *,
    batch_size: int,
    seed: int,
) -> CalibratedThreshold:
    """Bootstrap-calibrated on the MAX absolute composition shift across
    every (sex/education/marriage) x group pair per resample - the same
    family-wise-max pattern as `psi_family_wise`
    (`credlens.monitoring.calibration_study`), since sex/education/
    marriage together have several groups and checking each
    independently at its own 95th percentile would understate the true
    joint false-alert rate."""
    cfg = thresholds_config.subgroup_composition_drift_calibration
    n_resamples = int(cfg["n_resamples"])
    rng = np.random.default_rng(seed)
    n = len(reference_population)
    attributes = [a for a in ("sex", "education", "marriage") if a in reference_population.columns]
    reference_shares = {
        attribute: reference_population[attribute].value_counts(normalize=True).to_dict()
        for attribute in attributes
    }
    null: list[float] = []
    for _ in range(n_resamples):
        idx = rng.choice(n, size=min(batch_size, n), replace=False)
        subsample = reference_population.iloc[idx]
        max_shift = 0.0
        for attribute in attributes:
            shares = subsample[attribute].value_counts(normalize=True)
            for group, ref_share in reference_shares[attribute].items():
                observed_share = float(shares.get(group, 0.0))
                max_shift = max(max_shift, abs(observed_share - ref_share))
        null.append(max_shift)
    arr = np.array(null) if null else np.array([0.0])
    return CalibratedThreshold(
        metric="max_composition_shift",
        review_cutoff=float(np.percentile(arr, float(cfg["review_percentile"]))),
        material_deviation_cutoff=float(
            np.percentile(arr, float(cfg["material_deviation_percentile"]))
        ),
        n_resamples=len(null),
        batch_size=batch_size,
        min_sample_size_for_alert=int(thresholds_config.calibration["min_sample_size_for_alert"]),
    )


def write_calibrated_thresholds(
    reference_id: str, thresholds: dict[str, CalibratedThreshold], *, repo_root: Path | None = None
) -> Path:
    repo_root = repo_root or Path.cwd()
    out_dir = repo_root / "reports" / "monitoring" / "reference"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{reference_id}__alert_thresholds.json"
    path.write_text(
        json.dumps({k: v.to_dict() for k, v in thresholds.items()}, indent=2), encoding="utf-8"
    )
    return path


def load_calibrated_thresholds(
    reference_id: str, *, repo_root: Path | None = None
) -> dict[str, CalibratedThreshold]:
    repo_root = repo_root or Path.cwd()
    path = (
        repo_root
        / "reports"
        / "monitoring"
        / "reference"
        / f"{reference_id}__alert_thresholds.json"
    )
    if not path.is_file():
        raise ThresholdsError(f"No calibrated thresholds found at '{path}'.")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: CalibratedThreshold(**v) for k, v in raw.items()}
