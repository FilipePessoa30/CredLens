"""Phase 10 gate F - false-alert-rate calibration study.

An empirical audit (this module, run against the real 30,000-row UCI
benchmark) found that `credlens.monitoring.thresholds.calibrate_thresholds`'s
per-feature PSI calibration, while correct for a SINGLE feature considered
in isolation, produces a family-wise false-alert rate of ~60% across 100
genuinely unperturbed 500-row batches (>=1 of the 18 simultaneous
per-feature PSI checks firing) - each feature's 95th-percentile cutoff
only controls ITS OWN marginal false-alert rate, not the probability that
ANY of 18 simultaneous checks fires (a textbook multiple-comparisons
problem: 1-(0.95)^18 ~= 60%, matching the empirical measurement almost
exactly).

This module adds:
  - `generate_baseline_like_batches`: >=100 unperturbed i.i.d. samples of
    the SAME size as monitored batches, drawn from the locked TEST SET
    (the population real monitored batches come from - never the
    reference itself, which would be circular).
  - `calibrate_family_wise_psi_threshold`: a SEPARATE threshold calibrated
    on the MAX PSI across all features per resample, controlling the
    family-wise rate directly (Phase 10 gate F's "empirical max-based
    threshold").
  - `benjamini_hochberg`: FDR correction for ranking individual per-
    feature signals as exploratory candidates, without driving
    escalation on its own (gate F's "Benjamini-Hochberg for exploratory
    signals").
  - `run_false_alert_rate_study` / `run_batch_size_study`: orchestration
    that measures real false-alert rates before/after the family-wise
    correction, at one or several batch sizes.

Never touches the reference/thresholds JSON already written by `credlens
monitor create-reference` - this is a DIAGNOSTIC/CALIBRATION layer read
by `credlens monitor calibrate-reference`, which then writes the
family-wise threshold as an ADDITIONAL entry alongside the existing
per-feature ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from credlens.model_validation.discrimination import independent_roc_auc
from credlens.modeling.features import FEATURE_COLUMNS, engineer_features
from credlens.monitoring.batches import sorted_locked_test_set
from credlens.monitoring.drift import compute_feature_drift, population_stability_index
from credlens.monitoring.reference import MonitoringReference
from credlens.monitoring.thresholds import CalibratedThreshold, classify_state


class CalibrationStudyError(Exception):
    """Raised when the calibration study cannot run (missing reference/model)."""


def generate_baseline_like_batches(
    model_id: str, *, n_batches: int, batch_size: int, seed: int, repo_root: Path | None = None
) -> list[tuple[int, pd.DataFrame]]:
    """>=`n_batches` i.i.d. samples of `batch_size` rows, WITHOUT
    replacement within a batch but WITH overlap allowed ACROSS batches
    (the locked test set has only 6,000 rows - far fewer than
    `n_batches * batch_size` for realistic study sizes), from the SAME
    locked test set real monitored batches are partitioned from. No
    perturbation of any kind - these represent "what would a genuinely
    normal batch look like"."""
    repo_root = repo_root or Path.cwd()
    test_df = sorted_locked_test_set(model_id, repo_root=repo_root)
    if batch_size > len(test_df):
        raise CalibrationStudyError(
            f"batch_size ({batch_size}) exceeds the locked test set size ({len(test_df)})."
        )
    rng = np.random.default_rng(seed)
    batches = []
    for i in range(n_batches):
        idx = rng.choice(len(test_df), size=batch_size, replace=False)
        batches.append((i, test_df.iloc[idx].reset_index(drop=True)))
    return batches


def calibrate_family_wise_psi_threshold(
    reference_population: pd.DataFrame,
    reference: MonitoringReference,
    *,
    batch_size: int,
    feature_columns: list[str] | None = None,
    n_resamples: int,
    review_percentile: float,
    material_percentile: float,
    seed: int,
) -> CalibratedThreshold:
    """Family-wise null: for each resample, the MAX PSI across ALL
    `feature_columns` (not one randomly-chosen feature) - calibrating on
    this max statistic controls P(any feature's PSI exceeds the cutoff),
    directly fixing the multiple-comparisons inflation the per-feature
    calibration does not address."""
    feature_columns = feature_columns if feature_columns is not None else list(FEATURE_COLUMNS)
    rng = np.random.default_rng(seed)
    n = len(reference_population)
    max_psi_null: list[float] = []
    for _ in range(n_resamples):
        idx = rng.choice(n, size=min(batch_size, n), replace=False)
        max_psi = 0.0
        for feature in feature_columns:
            full = reference_population[feature].to_numpy(dtype=float)
            subsample = full[idx]
            bin_edges = reference.feature_stats[feature]["histogram"]["bin_edges"]
            psi = abs(population_stability_index(full, subsample, bin_edges))
            max_psi = max(max_psi, psi)
        max_psi_null.append(max_psi)
    arr = np.array(max_psi_null)
    return CalibratedThreshold(
        metric="psi_family_wise",
        review_cutoff=float(np.percentile(arr, review_percentile)),
        material_deviation_cutoff=float(np.percentile(arr, material_percentile)),
        n_resamples=n_resamples,
        batch_size=batch_size,
        min_sample_size_for_alert=30,
    )


def benjamini_hochberg(p_values: dict[str, float], fdr: float) -> dict[str, bool]:
    """Standard Benjamini-Hochberg step-up procedure: sorts p-values
    ascending, finds the largest k where p_(k) <= (k/m)*fdr, and flags
    every feature at or below that rank as BH-significant. Used here to
    rank individual per-feature drift signals as exploratory candidates
    for closer inspection - NEVER used on its own to decide alert-level
    escalation (that is the family-wise threshold's job, see module
    docstring) or incident status (that additionally requires
    consecutive-batch confirmation, gate G)."""
    items = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(items)
    significant: dict[str, bool] = dict.fromkeys(p_values, False)
    largest_k = 0
    for k, (_feature, p) in enumerate(items, start=1):
        if p <= (k / m) * fdr:
            largest_k = k
    for k, (feature, _p) in enumerate(items, start=1):
        significant[feature] = k <= largest_k
    return significant


def _empirical_p_value(observed: float, null_distribution: np.ndarray) -> float:
    n_at_or_above = int(np.sum(null_distribution >= observed))
    return (n_at_or_above + 1) / (len(null_distribution) + 1)


def _per_feature_marginal_null(
    reference_population: pd.DataFrame,
    reference: MonitoringReference,
    feature: str,
    *,
    batch_size: int,
    n_resamples: int,
    seed: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = len(reference_population)
    full = reference_population[feature].to_numpy(dtype=float)
    bin_edges = reference.feature_stats[feature]["histogram"]["bin_edges"]
    values = []
    for _ in range(n_resamples):
        idx = rng.choice(n, size=min(batch_size, n), replace=False)
        values.append(abs(population_stability_index(full, full[idx], bin_edges)))
    return np.array(values)


@dataclass(frozen=True)
class FalseAlertBatchResult:
    batch_index: int
    n_rows: int
    per_feature_psi: dict[str, float]
    per_feature_signal_fired: dict[str, bool]
    family_wise_max_psi: float
    family_wise_max_feature: str
    family_wise_signal_fired: bool
    family_wise_material_fired: bool
    score_mean_shift: float
    score_signal_fired: bool
    roc_auc_delta: float | None
    performance_signal_fired: bool
    any_marginal_signal_fired: bool
    any_family_wise_or_other_signal_fired: bool
    n_marginal_signals_fired: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_index": self.batch_index,
            "n_rows": self.n_rows,
            "per_feature_psi": {k: round(v, 6) for k, v in self.per_feature_psi.items()},
            "per_feature_signal_fired": self.per_feature_signal_fired,
            "family_wise_max_psi": round(self.family_wise_max_psi, 6),
            "family_wise_max_feature": self.family_wise_max_feature,
            "family_wise_signal_fired": self.family_wise_signal_fired,
            "family_wise_material_fired": self.family_wise_material_fired,
            "score_mean_shift": round(self.score_mean_shift, 6),
            "score_signal_fired": self.score_signal_fired,
            "roc_auc_delta": (
                round(self.roc_auc_delta, 6) if self.roc_auc_delta is not None else None
            ),
            "performance_signal_fired": self.performance_signal_fired,
            "any_marginal_signal_fired": self.any_marginal_signal_fired,
            "any_family_wise_or_other_signal_fired": self.any_family_wise_or_other_signal_fired,
            "n_marginal_signals_fired": self.n_marginal_signals_fired,
        }


@dataclass(frozen=True)
class FalseAlertRateStudyReport:
    reference_id: str
    n_batches: int
    batch_size: int
    seed: int
    source: str
    per_feature_false_alert_rate: dict[str, float]
    mean_marginal_signals_per_batch: float
    family_wise_marginal_rate: float
    family_wise_corrected_review_rate: float
    family_wise_corrected_material_rate: float
    score_false_alert_rate: float
    performance_false_alert_rate: float
    batch_results: list[FalseAlertBatchResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "n_batches": self.n_batches,
            "batch_size": self.batch_size,
            "seed": self.seed,
            "source": self.source,
            "per_feature_false_alert_rate": {
                k: round(v, 4) for k, v in self.per_feature_false_alert_rate.items()
            },
            "mean_marginal_signals_per_batch": round(self.mean_marginal_signals_per_batch, 4),
            "family_wise_marginal_rate": round(self.family_wise_marginal_rate, 4),
            "family_wise_corrected_review_rate": round(self.family_wise_corrected_review_rate, 4),
            "family_wise_corrected_material_rate": round(
                self.family_wise_corrected_material_rate, 4
            ),
            "score_false_alert_rate": round(self.score_false_alert_rate, 4),
            "performance_false_alert_rate": round(self.performance_false_alert_rate, 4),
            "batch_results": [b.to_dict() for b in self.batch_results],
        }


def run_false_alert_rate_study(
    reference_id: str,
    *,
    n_batches: int,
    batch_size: int,
    seed: int,
    family_wise_threshold: CalibratedThreshold,
    repo_root: Path | None = None,
) -> FalseAlertRateStudyReport:
    """Runs `n_batches` unperturbed baseline-like batches (from the
    locked test set) through the EXISTING per-feature marginal
    thresholds (unchanged) and the NEW family-wise threshold, measuring
    real false-alert rates for both - this is the empirical evidence
    gate F's recalibration decision rests on."""
    from credlens.modeling.registry import load_model_candidate
    from credlens.monitoring.reference import load_reference, load_reference_population
    from credlens.monitoring.thresholds import load_calibrated_thresholds

    repo_root = repo_root or Path.cwd()
    reference = load_reference(reference_id, repo_root=repo_root)
    reference_population = load_reference_population(reference_id, repo_root=repo_root)
    calibrated = load_calibrated_thresholds(reference_id, repo_root=repo_root)
    pipeline, manifest = load_model_candidate(
        reference.model_id, repo_root / "reports/modeling/models"
    )
    _ = manifest

    reference_roc_auc = independent_roc_auc(
        pd.Series(reference_population["y_true"].to_numpy()),
        pd.Series(reference_population["score"].to_numpy()),
    )

    batches = generate_baseline_like_batches(
        reference.model_id,
        n_batches=n_batches,
        batch_size=batch_size,
        seed=seed,
        repo_root=repo_root,
    )

    per_feature_fires: dict[str, int] = dict.fromkeys(FEATURE_COLUMNS, 0)
    total_marginal_signals = 0
    family_wise_review_hits = 0
    family_wise_material_hits = 0
    score_fires = 0
    performance_fires = 0
    batch_results: list[FalseAlertBatchResult] = []

    for batch_index, raw_batch in batches:
        engineered = engineer_features(raw_batch)[list(FEATURE_COLUMNS)]
        per_feature_psi: dict[str, float] = {}
        per_feature_fired: dict[str, bool] = {}
        max_psi = 0.0
        max_feature = ""
        for feature in FEATURE_COLUMNS:
            ref_values = reference_population[feature].to_numpy(dtype=float)
            drift = compute_feature_drift(
                feature,
                ref_values,
                engineered[feature].to_numpy(dtype=float),
                reference.feature_stats[feature],
                reference.feature_stats[feature]["histogram"]["bin_edges"],
            )
            per_feature_psi[feature] = drift.psi
            state = classify_state(abs(drift.psi), calibrated["psi"], len(engineered))
            fired = state != "within_reference_variability"
            per_feature_fired[feature] = fired
            if fired:
                per_feature_fires[feature] += 1
                total_marginal_signals += 1
            if abs(drift.psi) > max_psi:
                max_psi = abs(drift.psi)
                max_feature = feature

        family_wise_state = classify_state(max_psi, family_wise_threshold, len(engineered))
        family_wise_signal_fired = family_wise_state != "within_reference_variability"
        family_wise_material_fired = family_wise_state == "material_deviation"
        if family_wise_signal_fired:
            family_wise_review_hits += 1
        if family_wise_material_fired:
            family_wise_material_hits += 1

        pipeline_scores = pipeline.predict_proba(engineered)[:, 1]
        score_mean_shift = float(pipeline_scores.mean() - reference_population["score"].mean())
        score_state = classify_state(
            abs(score_mean_shift), calibrated["score_mean_shift"], len(pipeline_scores)
        )
        score_fired = score_state != "within_reference_variability"
        if score_fired:
            score_fires += 1
            total_marginal_signals += 1

        y_batch = raw_batch["Y"].to_numpy()
        roc_auc_delta: float | None = None
        performance_fired = False
        if len(set(y_batch.tolist())) >= 2:
            batch_roc_auc = independent_roc_auc(pd.Series(y_batch), pd.Series(pipeline_scores))
            roc_auc_delta = batch_roc_auc - reference_roc_auc
            perf_state = classify_state(
                abs(roc_auc_delta), calibrated["roc_auc_delta"], len(y_batch)
            )
            performance_fired = perf_state != "within_reference_variability"
            if performance_fired:
                performance_fires += 1
                total_marginal_signals += 1

        n_marginal = sum(per_feature_fired.values()) + int(score_fired) + int(performance_fired)
        batch_results.append(
            FalseAlertBatchResult(
                batch_index=batch_index,
                n_rows=len(raw_batch),
                per_feature_psi=per_feature_psi,
                per_feature_signal_fired=per_feature_fired,
                family_wise_max_psi=max_psi,
                family_wise_max_feature=max_feature,
                family_wise_signal_fired=family_wise_signal_fired,
                family_wise_material_fired=family_wise_material_fired,
                score_mean_shift=score_mean_shift,
                score_signal_fired=score_fired,
                roc_auc_delta=roc_auc_delta,
                performance_signal_fired=performance_fired,
                any_marginal_signal_fired=n_marginal > 0,
                any_family_wise_or_other_signal_fired=(
                    family_wise_signal_fired or score_fired or performance_fired
                ),
                n_marginal_signals_fired=n_marginal,
            )
        )

    n = len(batch_results)
    family_wise_marginal_rate = sum(1 for b in batch_results if b.any_marginal_signal_fired) / n
    return FalseAlertRateStudyReport(
        reference_id=reference_id,
        n_batches=n,
        batch_size=batch_size,
        seed=seed,
        source="locked_test_set_iid_resample",
        per_feature_false_alert_rate={f: c / n for f, c in per_feature_fires.items()},
        mean_marginal_signals_per_batch=total_marginal_signals / n,
        family_wise_marginal_rate=family_wise_marginal_rate,
        family_wise_corrected_review_rate=family_wise_review_hits / n,
        family_wise_corrected_material_rate=family_wise_material_hits / n,
        score_false_alert_rate=score_fires / n,
        performance_false_alert_rate=performance_fires / n,
        batch_results=batch_results,
    )


@dataclass(frozen=True)
class BatchSizeStudyRow:
    batch_size: int
    family_wise_review_cutoff: float
    family_wise_material_cutoff: float
    family_wise_marginal_rate: float
    family_wise_corrected_review_rate: float
    family_wise_corrected_material_rate: float
    roc_auc_delta_p2_5_p97_5_width: float
    mean_marginal_signals_per_batch: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_size": self.batch_size,
            "family_wise_review_cutoff": round(self.family_wise_review_cutoff, 6),
            "family_wise_material_cutoff": round(self.family_wise_material_cutoff, 6),
            "family_wise_marginal_rate": round(self.family_wise_marginal_rate, 4),
            "family_wise_corrected_review_rate": round(self.family_wise_corrected_review_rate, 4),
            "family_wise_corrected_material_rate": round(
                self.family_wise_corrected_material_rate, 4
            ),
            "roc_auc_delta_p2_5_p97_5_width": round(self.roc_auc_delta_p2_5_p97_5_width, 6),
            "mean_marginal_signals_per_batch": round(self.mean_marginal_signals_per_batch, 4),
        }


def run_batch_size_study(
    reference_id: str,
    *,
    batch_sizes: list[int],
    n_batches_per_size: int,
    n_resamples_for_family_wise: int,
    review_percentile: float,
    material_percentile: float,
    seed: int,
    repo_root: Path | None = None,
) -> list[BatchSizeStudyRow]:
    """Re-measures false-alert rates (this module's core deliverable) and
    natural batch-to-batch performance variability at each of
    `batch_sizes` - the empirical basis for a demonstrative minimum
    sample size per metric class (Phase 10's batch-size study). Detection
    POWER against real perturbation scenarios is evaluated separately, at
    the standard 500-row size, by `credlens.monitoring.detection_eval`
    (re-running all 12 scenarios at every batch size would require
    rebuilding the scenario batches themselves at each size, which is out
    of scope for this diagnostic study)."""
    from credlens.monitoring.reference import load_reference, load_reference_population

    repo_root = repo_root or Path.cwd()
    reference = load_reference(reference_id, repo_root=repo_root)
    reference_population = load_reference_population(reference_id, repo_root=repo_root)

    rows = []
    for batch_size in batch_sizes:
        family_wise = calibrate_family_wise_psi_threshold(
            reference_population,
            reference,
            batch_size=batch_size,
            n_resamples=n_resamples_for_family_wise,
            review_percentile=review_percentile,
            material_percentile=material_percentile,
            seed=seed,
        )
        study = run_false_alert_rate_study(
            reference_id,
            n_batches=n_batches_per_size,
            batch_size=batch_size,
            seed=seed,
            family_wise_threshold=family_wise,
            repo_root=repo_root,
        )
        roc_auc_deltas = [
            b.roc_auc_delta for b in study.batch_results if b.roc_auc_delta is not None
        ]
        width = (
            float(np.percentile(roc_auc_deltas, 97.5) - np.percentile(roc_auc_deltas, 2.5))
            if len(roc_auc_deltas) > 2
            else float("nan")
        )
        rows.append(
            BatchSizeStudyRow(
                batch_size=batch_size,
                family_wise_review_cutoff=family_wise.review_cutoff,
                family_wise_material_cutoff=family_wise.material_deviation_cutoff,
                family_wise_marginal_rate=study.family_wise_marginal_rate,
                family_wise_corrected_review_rate=study.family_wise_corrected_review_rate,
                family_wise_corrected_material_rate=study.family_wise_corrected_material_rate,
                roc_auc_delta_p2_5_p97_5_width=width,
                mean_marginal_signals_per_batch=study.mean_marginal_signals_per_batch,
            )
        )
    return rows
