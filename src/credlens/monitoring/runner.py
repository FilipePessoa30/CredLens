"""Orchestrates one monitoring run (Phase 9 section 20) - reads a
reference + a batch set, and for every batch: profiles data quality
(`audit` mode, never blocking), re-checks it in `strict` mode to decide
whether scoring may proceed at all, engineers features, scores with the
already-frozen registered model, computes feature/score/performance/
subgroup drift against the reference, and raises alerts only where the
calibrated thresholds are exceeded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from credlens.model_validation.calibration import independent_brier
from credlens.model_validation.discrimination import independent_pr_auc, independent_roc_auc
from credlens.modeling.features import FEATURE_COLUMNS, engineer_features
from credlens.modeling.input_contract import InputContractError, validate_input_contract
from credlens.modeling.registry import load_model_candidate
from credlens.monitoring.alerts import Alert, build_alert, build_blocked_input_alert, write_alerts
from credlens.monitoring.batches import load_batch, load_batch_manifest, load_unperturbed_partition
from credlens.monitoring.data_quality import compute_data_quality
from credlens.monitoring.drift import compute_feature_drift
from credlens.monitoring.performance import LABELS_PENDING, compute_performance_drift
from credlens.monitoring.provenance import MONITORING_SIMULATION_LABEL_EN
from credlens.monitoring.reference import (
    MonitoringReference,
    load_reference,
    load_reference_population,
)
from credlens.monitoring.score_monitoring import compute_score_drift
from credlens.monitoring.subgroup import compute_subgroup_monitoring
from credlens.monitoring.thresholds import CalibratedThreshold, load_calibrated_thresholds

MODELS_DIR = Path("reports/modeling/models")
MODELING_TABLES_DIR = Path("reports/modeling/tables")
RUNS_DIR = Path("reports/monitoring/runs")


class MonitoringRunError(Exception):
    """Raised for reference/batch-set/threshold lookup failures."""


def _top10_threshold(experiment_id: str, repo_root: Path) -> float:
    path = repo_root / MODELING_TABLES_DIR / f"{experiment_id}__thresholds.csv"
    table = pd.read_csv(path)
    return float(table[table["name"] == "top_10_pct"].iloc[0]["threshold"])


@dataclass(frozen=True)
class BatchRunResult:
    batch_sequence: int
    simulation_scenario: str
    source_partition: int
    label_availability: str
    blocked: bool
    n_rows: int
    n_quarantined: int
    data_quality: dict[str, Any]
    feature_drift: list[dict[str, Any]]
    score_drift: dict[str, Any] | None
    performance_drift: dict[str, Any] | str
    subgroup_monitoring: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_sequence": self.batch_sequence,
            "simulation_scenario": self.simulation_scenario,
            "source_partition": self.source_partition,
            "label_availability": self.label_availability,
            "blocked": self.blocked,
            "n_rows": self.n_rows,
            "n_quarantined": self.n_quarantined,
            "data_quality": self.data_quality,
            "feature_drift": self.feature_drift,
            "score_drift": self.score_drift,
            "performance_drift": self.performance_drift,
            "subgroup_monitoring": self.subgroup_monitoring,
        }


def _process_batch(
    spec: dict[str, Any],
    raw_batch: pd.DataFrame,
    *,
    reference: MonitoringReference,
    reference_population: pd.DataFrame,
    pipeline: Any,
    manifest: Any,
    calibrated: dict[str, CalibratedThreshold],
    top10_threshold: float,
    run_id: str,
    repo_root: Path,
) -> tuple[BatchRunResult, list[Alert]]:
    batch_sequence = int(spec["batch_sequence"])
    alerts: list[Alert] = []

    audit_report = validate_input_contract(raw_batch, "audit")
    data_quality = compute_data_quality(raw_batch, audit_report)

    try:
        strict_report = validate_input_contract(raw_batch, "strict")
    except InputContractError as exc:
        alerts.append(
            build_blocked_input_alert(
                run_id=run_id,
                batch_sequence=batch_sequence,
                model_id=manifest.model_id,
                detail=str(exc),
            )
        )
        return (
            BatchRunResult(
                batch_sequence=batch_sequence,
                simulation_scenario=spec["simulation_scenario"],
                source_partition=int(spec["source_partition"]),
                label_availability=spec["label_availability"],
                blocked=True,
                n_rows=len(raw_batch),
                n_quarantined=len(raw_batch),
                data_quality=data_quality.to_dict(),
                feature_drift=[],
                score_drift=None,
                performance_drift="blocked_input",
                subgroup_monitoring=[],
            ),
            alerts,
        )

    from credlens.modeling.input_contract import clean_rows, write_quarantine

    clean_batch = clean_rows(raw_batch, strict_report)
    if strict_report.n_quarantined_rows > 0:
        write_quarantine(raw_batch, strict_report, repo_root=repo_root)

    engineered = engineer_features(clean_batch)[FEATURE_COLUMNS]
    scores = pipeline.predict_proba(engineered)[:, 1]

    feature_drift_results = []
    for feature in FEATURE_COLUMNS:
        reference_values = reference_population[feature].to_numpy(dtype=float)
        drift = compute_feature_drift(
            feature,
            reference_values,
            engineered[feature].to_numpy(dtype=float),
            reference.feature_stats[feature],
            reference.feature_stats[feature]["histogram"]["bin_edges"],
        )
        feature_drift_results.append(drift.to_dict())
        if "psi" in calibrated:
            alert = build_alert(
                run_id=run_id,
                batch_sequence=batch_sequence,
                model_id=manifest.model_id,
                category="feature_drift",
                metric=f"psi__{feature}",
                reference_value=0.0,
                observed_value=drift.psi,
                calibrated=calibrated["psi"],
                sample_size=len(engineered),
            )
            if alert is not None:
                alerts.append(alert)

    # Phase 10 gate F - family-wise check: `calibrated["psi"]` above only
    # controls EACH feature's OWN marginal false-alert rate; checking 18
    # features independently at that same marginal cutoff produces a
    # ~60% family-wise false-alert rate (empirically measured - see
    # credlens.monitoring.calibration_study module docstring). This
    # SEPARATE check, against a threshold calibrated on the MAX PSI
    # across all features (only present once `credlens monitor
    # calibrate-reference` has been run), is what gate G/H's incident/
    # severity logic uses to decide whether a batch's feature drift is
    # family-wise significant - never a substitute for the per-feature
    # alerts above, which remain untouched and keep firing at the same
    # rate as before.
    if "psi_family_wise" in calibrated and feature_drift_results:
        max_psi_row = max(feature_drift_results, key=lambda d: abs(d["psi"]))
        family_wise_alert = build_alert(
            run_id=run_id,
            batch_sequence=batch_sequence,
            model_id=manifest.model_id,
            category="feature_drift",
            metric=f"psi_family_wise__{max_psi_row['feature']}",
            reference_value=0.0,
            observed_value=max_psi_row["psi"],
            calibrated=calibrated["psi_family_wise"],
            sample_size=len(engineered),
        )
        if family_wise_alert is not None:
            alerts.append(family_wise_alert)

    # Rank stability needs an unperturbed "twin" scoring of the exact same
    # rows; batches that change row membership/count (prevalence_drift,
    # subgroup_composition_shift, corrupted_schema) have no valid twin, so
    # this stays `None` for those rather than being paired incorrectly.
    baseline_scores_same_rows = None
    if (
        spec["simulation_scenario"]
        not in ("prevalence_drift", "subgroup_composition_shift", "corrupted_schema")
        and strict_report.n_quarantined_rows == 0
    ):
        unperturbed = load_unperturbed_partition(
            manifest.model_id, int(spec["source_partition"]), len(raw_batch), repo_root=repo_root
        )
        unperturbed_features = engineer_features(unperturbed)[FEATURE_COLUMNS]
        baseline_scores_same_rows = pipeline.predict_proba(unperturbed_features)[:, 1]

    score_drift = compute_score_drift(
        reference_population["score"].to_numpy(dtype=float),
        scores,
        reference_score_stats=reference.score_stats,
        risk_band_cuts=manifest.risk_band_cuts,
        reference_risk_band_distribution=reference.risk_band_distribution,
        top10_threshold=top10_threshold,
        baseline_scores_same_rows=baseline_scores_same_rows,
    )
    if "score_mean_shift" in calibrated:
        alert = build_alert(
            run_id=run_id,
            batch_sequence=batch_sequence,
            model_id=manifest.model_id,
            category="score_drift",
            metric="score_mean_shift",
            reference_value=reference.score_stats["mean"],
            observed_value=float(scores.mean()),
            calibrated=calibrated["score_mean_shift"],
            sample_size=len(scores),
        )
        if alert is not None:
            alerts.append(alert)

    performance_drift: dict[str, Any] | str
    if spec["label_availability"] == "available" and "Y" in clean_batch.columns:
        y_batch = clean_batch["Y"].reset_index(drop=True)
        p_batch = pd.Series(scores)
        # Phase 10 gate F performance-reference audit: train+validation
        # combined is a systematically OPTIMISTIC performance reference
        # point (train dominates it and the model was fit on train) -
        # `reference.performance_reference` (validation-only, computed at
        # `credlens monitor create-reference` time - see
        # credlens.monitoring.reference module) is used here instead when
        # present. Falls back to recomputing from the combined population
        # for a reference built before this field existed.
        if reference.performance_reference:
            reference_roc_auc = float(reference.performance_reference["roc_auc"])
            reference_pr_auc = float(reference.performance_reference["pr_auc"])
            reference_brier = float(reference.performance_reference["brier"])
        else:
            y_full = reference_population["y_true"].to_numpy()
            p_full = reference_population["score"].to_numpy()
            reference_roc_auc = independent_roc_auc(pd.Series(y_full), pd.Series(p_full))
            reference_pr_auc = independent_pr_auc(pd.Series(y_full), pd.Series(p_full))
            reference_brier = independent_brier(pd.Series(y_full), pd.Series(p_full))
        try:
            perf = compute_performance_drift(
                y_batch,
                p_batch,
                threshold=top10_threshold,
                reference_roc_auc=reference_roc_auc,
                reference_pr_auc=reference_pr_auc,
                reference_brier=reference_brier,
            )
            performance_drift = perf.to_dict()
            if "roc_auc_delta" in calibrated:
                alert = build_alert(
                    run_id=run_id,
                    batch_sequence=batch_sequence,
                    model_id=manifest.model_id,
                    category="performance_drift",
                    metric="roc_auc_delta",
                    reference_value=reference_roc_auc,
                    observed_value=perf.roc_auc,
                    calibrated=calibrated["roc_auc_delta"],
                    sample_size=len(y_batch),
                )
                if alert is not None:
                    alerts.append(alert)
        except ValueError:
            performance_drift = LABELS_PENDING
    else:
        performance_drift = LABELS_PENDING

    subgroup_results = compute_subgroup_monitoring(
        clean_batch.reset_index(drop=True),
        scores,
        threshold=top10_threshold,
        reference_composition=reference.subgroup_composition,
        y_batch=(
            clean_batch["Y"].reset_index(drop=True)
            if spec["label_availability"] == "available" and "Y" in clean_batch.columns
            else None
        ),
    )

    return (
        BatchRunResult(
            batch_sequence=batch_sequence,
            simulation_scenario=spec["simulation_scenario"],
            source_partition=int(spec["source_partition"]),
            label_availability=spec["label_availability"],
            blocked=False,
            n_rows=len(raw_batch),
            n_quarantined=strict_report.n_quarantined_rows,
            data_quality=data_quality.to_dict(),
            feature_drift=feature_drift_results,
            score_drift=score_drift.to_dict(),
            performance_drift=performance_drift,
            subgroup_monitoring=[s.to_dict() for s in subgroup_results],
        ),
        alerts,
    )


def run_monitoring(
    reference_id: str, batch_set_id: str, *, repo_root: Path | None = None
) -> tuple[str, list[BatchRunResult], list[Alert]]:
    repo_root = repo_root or Path.cwd()
    reference = load_reference(reference_id, repo_root=repo_root)
    reference_population = load_reference_population(reference_id, repo_root=repo_root)
    pipeline, manifest = load_model_candidate(reference.model_id, repo_root / MODELS_DIR)
    calibrated = load_calibrated_thresholds(reference_id, repo_root=repo_root)
    top10_threshold = _top10_threshold(reference.experiment_id, repo_root)

    batch_manifest = load_batch_manifest(batch_set_id, repo_root=repo_root)
    run_id = f"RUN_{batch_set_id}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}"

    all_results: list[BatchRunResult] = []
    all_alerts: list[Alert] = []
    for spec in batch_manifest["batches"]:
        raw_batch = load_batch(batch_set_id, int(spec["batch_sequence"]), repo_root=repo_root)
        result, alerts = _process_batch(
            spec,
            raw_batch,
            reference=reference,
            reference_population=reference_population,
            pipeline=pipeline,
            manifest=manifest,
            calibrated=calibrated,
            top10_threshold=top10_threshold,
            run_id=run_id,
            repo_root=repo_root,
        )
        all_results.append(result)
        all_alerts.extend(alerts)

    out_dir = repo_root / RUNS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    run_record = {
        "run_id": run_id,
        "reference_id": reference_id,
        "batch_set_id": batch_set_id,
        "model_id": reference.model_id,
        "label_en": MONITORING_SIMULATION_LABEL_EN,
        "n_batches": len(all_results),
        "n_alerts": len(all_alerts),
        "batches": [r.to_dict() for r in all_results],
        "created_at_utc": datetime.now(UTC).isoformat(),
    }
    (out_dir / "run.json").write_text(json.dumps(run_record, indent=2), encoding="utf-8")
    write_alerts(run_id, all_alerts, repo_root=repo_root)

    return run_id, all_results, all_alerts


def load_run(run_id: str, *, repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root or Path.cwd()
    path = repo_root / RUNS_DIR / run_id / "run.json"
    if not path.is_file():
        raise MonitoringRunError(f"No monitoring run found at '{path}'.")
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return result
