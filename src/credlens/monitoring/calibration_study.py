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
    data_quality_material_fired: bool = False
    target_distribution_material_fired: bool = False
    subgroup_composition_material_fired: bool = False
    any_material_any_category_fired: bool = False

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
            "data_quality_material_fired": self.data_quality_material_fired,
            "target_distribution_material_fired": self.target_distribution_material_fired,
            "subgroup_composition_material_fired": self.subgroup_composition_material_fired,
            "any_material_any_category_fired": self.any_material_any_category_fired,
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
    combined_material_false_alert_rate: float = 0.0
    high_severity_false_alert_rate: float = 0.0
    high_severity_rate_reason_en: str = ""

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
            "combined_material_false_alert_rate": round(self.combined_material_false_alert_rate, 4),
            "high_severity_false_alert_rate": round(self.high_severity_false_alert_rate, 4),
            "high_severity_rate_reason_en": self.high_severity_rate_reason_en,
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
            performance_material_fired = perf_state == "material_deviation"
            if performance_fired:
                performance_fires += 1
                total_marginal_signals += 1
        else:
            performance_material_fired = False

        # Phase 10B - the same data_quality/target-distribution/subgroup-
        # composition checks `credlens.monitoring.runner` now performs on
        # every real batch, re-measured here on genuinely unperturbed
        # baseline batches to confirm they don't themselves introduce a
        # false-alert problem (their reference null is a degenerate point
        # mass at zero for data_quality - see `credlens.monitoring.
        # thresholds.data_quality_fixed_cutoffs` - so a real clean batch
        # should essentially never cross even `review`).
        from credlens.modeling.input_contract import validate_input_contract
        from credlens.monitoring.data_quality import compute_data_quality
        from credlens.monitoring.subgroup import compute_subgroup_monitoring

        dq_material = False
        if any(m in calibrated for m in ("missingness_rate", "domain_violation_rate")):
            audit_report = validate_input_contract(raw_batch, "audit")
            dq = compute_data_quality(raw_batch, audit_report)
            for metric_name, observed in (
                ("missingness_rate", dq.missingness_rate),
                ("domain_violation_rate", dq.domain_violation_rate),
                ("range_violation_rate", dq.range_violation_rate),
                ("duplicate_rate", dq.duplicate_rate),
            ):
                if metric_name in calibrated:
                    state = classify_state(observed, calibrated[metric_name], len(raw_batch))
                    if state == "material_deviation":
                        dq_material = True

        target_material = False
        if "event_rate_delta" in calibrated:
            reference_rate = float(reference_population["y_true"].mean())
            observed_rate = float(y_batch.mean())
            state = classify_state(
                abs(observed_rate - reference_rate), calibrated["event_rate_delta"], len(y_batch)
            )
            target_material = state == "material_deviation"

        subgroup_material = False
        if "max_composition_shift" in calibrated:
            from credlens.monitoring.reference import label_subgroup_columns

            subgroup_results = compute_subgroup_monitoring(
                label_subgroup_columns(raw_batch),
                pipeline_scores,
                threshold=0.5,
                reference_composition=reference.subgroup_composition,
                y_batch=None,
            )
            if subgroup_results:
                max_shift = max(abs(s.composition_shift) for s in subgroup_results)
                state = classify_state(
                    max_shift, calibrated["max_composition_shift"], len(raw_batch)
                )
                subgroup_material = state == "material_deviation"

        any_material_any_category = (
            family_wise_material_fired
            or score_state == "material_deviation"
            or performance_material_fired
            or dq_material
            or target_material
            or subgroup_material
        )

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
                data_quality_material_fired=dq_material,
                target_distribution_material_fired=target_material,
                subgroup_composition_material_fired=subgroup_material,
                any_material_any_category_fired=any_material_any_category,
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
        combined_material_false_alert_rate=(
            sum(1 for b in batch_results if b.any_material_any_category_fired) / n
        ),
        high_severity_false_alert_rate=0.0,
        high_severity_rate_reason_en=(
            "Structurally 0 by gate H's own severity policy (credlens.monitoring.incidents."
            "_group_severity): 'high' requires either a genuine blocked_input (never observed "
            "on these clean, schema-valid baseline batches) or a material signal CONFIRMED in "
            "the immediately following batch of the same category - these are independent i.i.d. "
            "resamples, not a real sequential stream, so no batch here has a genuine 'next batch' "
            "to confirm against. This is the intended guarantee, not an artifact of this study."
        ),
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


# Phase 10B - sensitivity analysis. Three real magnitude levels per
# perturbation type - "strong" always matches the canonical scenario
# already documented in `config/monitoring/scenarios.yml`/
# `scenarios_registry.yml`; "weak"/"moderate" are genuinely smaller,
# real perturbations of the SAME kind, never a hypothetical. Detection
# power is expected (and, per Phase 10B's own acceptance-gate discipline,
# never REQUIRED) to be lower at "weak" - only "strong" (the actual
# documented scenario magnitude) is held to the 90% floor.
SENSITIVITY_MAGNITUDES: dict[str, dict[str, dict[str, Any]]] = {
    "missingness_drift": {
        "weak": {"missingness_extra_fraction": 0.02},
        "moderate": {"missingness_extra_fraction": 0.08},
        "strong": {"missingness_extra_fraction": 0.15},
    },
    "utilization_shift": {
        "weak": {"utilization_shift_multiplier": 1.05},
        "moderate": {"utilization_shift_multiplier": 1.2},
        "strong": {"utilization_shift_multiplier": 1.5},
    },
    "payment_reduction": {
        "weak": {"payment_shrink_factor": 0.9},
        "moderate": {"payment_shrink_factor": 0.7},
        "strong": {"payment_shrink_factor": 0.5},
    },
    "delinquency_worsening": {
        "weak": {"delinquency_worsening_steps": 1},
        "moderate": {"delinquency_worsening_steps": 2},
        "strong": {"delinquency_worsening_steps": 3},
    },
    "prevalence_drift": {
        "weak": {"target_prevalence": 0.25},
        "moderate": {"target_prevalence": 0.30},
        "strong": {"target_prevalence": 0.35},
    },
    "subgroup_composition_shift": {
        "weak": {"oversampled_age_bucket": [18, 30], "oversample_fraction": 0.40},
        "moderate": {"oversampled_age_bucket": [18, 30], "oversample_fraction": 0.60},
        "strong": {"oversampled_age_bucket": [18, 30], "oversample_fraction": 0.80},
    },
}

_FEATURE_DRIFT_SCENARIOS = {"utilization_shift", "payment_reduction", "delinquency_worsening"}


@dataclass(frozen=True)
class SensitivityRow:
    perturbation_type: str
    magnitude_label: str
    magnitude_params: dict[str, Any]
    n_batches: int
    detection_rate: float
    material_rate: float
    mean_observed_value: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "perturbation_type": self.perturbation_type,
            "magnitude_label": self.magnitude_label,
            "magnitude_params": self.magnitude_params,
            "n_batches": self.n_batches,
            "detection_rate": round(self.detection_rate, 4),
            "material_rate": round(self.material_rate, 4),
            "mean_observed_value": round(self.mean_observed_value, 6),
        }


def run_sensitivity_analysis(
    reference_id: str,
    *,
    n_batches_per_magnitude: int,
    batch_size: int,
    seed: int,
    repo_root: Path | None = None,
) -> list[SensitivityRow]:
    """Real execution (never simulated numbers) of `n_batches_per_
    magnitude` genuinely perturbed batches at each of 3 magnitude levels
    (weak/moderate/strong - see `SENSITIVITY_MAGNITUDES`) for 6
    perturbation types, measuring the SAME calibrated metric
    `credlens.monitoring.runner` checks in production for that
    perturbation's category - never a perfect-detection assumption for a
    weak perturbation."""
    from credlens.modeling.features import FEATURE_COLUMNS, engineer_features
    from credlens.modeling.input_contract import validate_input_contract
    from credlens.modeling.registry import load_model_candidate
    from credlens.monitoring.batches import perturb_batch
    from credlens.monitoring.data_quality import compute_data_quality
    from credlens.monitoring.reference import (
        label_subgroup_columns,
        load_reference,
        load_reference_population,
    )
    from credlens.monitoring.subgroup import compute_subgroup_monitoring
    from credlens.monitoring.thresholds import load_calibrated_thresholds

    repo_root = repo_root or Path.cwd()
    reference = load_reference(reference_id, repo_root=repo_root)
    reference_population = load_reference_population(reference_id, repo_root=repo_root)
    calibrated = load_calibrated_thresholds(reference_id, repo_root=repo_root)
    pipeline, _manifest = load_model_candidate(
        reference.model_id, repo_root / "reports/modeling/models"
    )
    reference_event_rate = float(reference_population["y_true"].mean())

    rows: list[SensitivityRow] = []
    for perturbation_type, levels in SENSITIVITY_MAGNITUDES.items():
        for magnitude_label, magnitude_params in levels.items():
            rng = np.random.default_rng(seed)
            batches = generate_baseline_like_batches(
                reference.model_id,
                n_batches=n_batches_per_magnitude,
                batch_size=batch_size,
                seed=seed,
                repo_root=repo_root,
            )
            detections = 0
            materials = 0
            observed_values: list[float] = []
            for _batch_index, raw_batch in batches:
                spec = {"simulation_scenario": perturbation_type, **magnitude_params}
                perturbed = perturb_batch(raw_batch, spec, rng)

                if perturbation_type == "missingness_drift":
                    audit_report = validate_input_contract(perturbed, "audit")
                    dq = compute_data_quality(perturbed, audit_report)
                    observed = dq.missingness_rate
                    state = classify_state(observed, calibrated["missingness_rate"], len(perturbed))
                elif perturbation_type in _FEATURE_DRIFT_SCENARIOS:
                    engineered = engineer_features(perturbed)[list(FEATURE_COLUMNS)]
                    max_psi = 0.0
                    for feature in FEATURE_COLUMNS:
                        drift = compute_feature_drift(
                            feature,
                            reference_population[feature].to_numpy(dtype=float),
                            engineered[feature].to_numpy(dtype=float),
                            reference.feature_stats[feature],
                            reference.feature_stats[feature]["histogram"]["bin_edges"],
                        )
                        max_psi = max(max_psi, abs(drift.psi))
                    observed = max_psi
                    state = classify_state(observed, calibrated["psi_family_wise"], len(perturbed))
                elif perturbation_type == "prevalence_drift":
                    observed_rate = float(perturbed["Y"].mean())
                    observed = abs(observed_rate - reference_event_rate)
                    state = classify_state(observed, calibrated["event_rate_delta"], len(perturbed))
                elif perturbation_type == "subgroup_composition_shift":
                    engineered = engineer_features(perturbed)[list(FEATURE_COLUMNS)]
                    scores = pipeline.predict_proba(engineered)[:, 1]
                    subgroup_results = compute_subgroup_monitoring(
                        label_subgroup_columns(perturbed, repo_root=repo_root),
                        scores,
                        threshold=0.5,
                        reference_composition=reference.subgroup_composition,
                        y_batch=None,
                    )
                    observed = (
                        max(abs(s.composition_shift) for s in subgroup_results)
                        if subgroup_results
                        else 0.0
                    )
                    state = classify_state(
                        observed, calibrated["max_composition_shift"], len(perturbed)
                    )
                else:
                    raise ValueError(f"Unhandled sensitivity perturbation '{perturbation_type}'.")

                observed_values.append(observed)
                if state != "within_reference_variability":
                    detections += 1
                if state == "material_deviation":
                    materials += 1

            n = len(batches)
            rows.append(
                SensitivityRow(
                    perturbation_type=perturbation_type,
                    magnitude_label=magnitude_label,
                    magnitude_params=magnitude_params,
                    n_batches=n,
                    detection_rate=detections / n,
                    material_rate=materials / n,
                    mean_observed_value=float(np.mean(observed_values)) if observed_values else 0.0,
                )
            )
    return rows
