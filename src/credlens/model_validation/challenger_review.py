"""Formalizes the HistGradientBoosting model as a registered `challenger`
(Phase 9 section 8) - Phase 8 evaluated it but never registered an
artifact/manifest for it. Registration here mirrors
`credlens.modeling.registry.register_model_candidate` but writes
`status="challenger"` (never `candidate`, never `production`) and is
never called by the Phase 8 gate-eligibility path.

`build_pareto_comparison` (section 8.1) runs the SAME diagnostics Phase 8
ran for the candidate (split-stability sweep, robustness suite, subgroup
audit) against the challenger too, since Phase 8 only ever evaluated its
point-in-time test metrics - a fair trade-off table needs the same axes
on both sides.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from credlens.data.checksums import compute_sha256
from credlens.model_validation.subgroup_validation import run_subgroup_validation
from credlens.modeling.contracts import EvaluationConfig, FeatureRegistry, TargetContract
from credlens.modeling.features import FEATURE_COLUMNS
from credlens.modeling.registry import ModelCandidateManifest
from credlens.modeling.robustness import run_robustness_suite
from credlens.modeling.training import FittedModel, predict_proba_positive
from credlens.modeling.uncertainty import split_stability_sweep

CHALLENGER_STATUS = "challenger"  # never "candidate", never "production"


def register_challenger(
    fitted: FittedModel,
    *,
    model_id: str,
    experiment_id: str,
    output_dir: Path,
    feature_registry_version: str,
    test_metrics: dict[str, Any],
    limitations: list[str],
    benchmark_source_id: str = "uci-default-credit",
) -> ModelCandidateManifest:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_filename = f"{model_id}.joblib"
    artifact_path = output_dir / artifact_filename
    joblib.dump(fitted.pipeline, artifact_path)
    artifact_hash = compute_sha256(artifact_path)

    manifest = ModelCandidateManifest(
        model_id=model_id,
        status=CHALLENGER_STATUS,
        experiment_id=experiment_id,
        artifact_relative_path=artifact_filename,
        artifact_sha256=artifact_hash,
        input_schema=dict.fromkeys(fitted.feature_columns, "float64"),
        output_schema={
            "pseudonymous_record_id": "string",
            "predicted_default_probability": "float64",
            "risk_band": "string",
            "model_version": "string",
            "scoring_timestamp": "string",
            "input_schema_version": "string",
        },
        benchmark_source_id=benchmark_source_id,
        feature_registry_version=feature_registry_version,
        test_metrics=test_metrics,
        limitations=limitations,
        risk_band_cuts=[],
    )
    manifest_path = output_dir / f"{model_id}.manifest.json"
    import json

    manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
    return manifest


def _measure_latency_ms(fitted: FittedModel, x: pd.DataFrame, *, n_repeats: int = 5) -> float:
    durations = []
    for _ in range(n_repeats):
        started = time.perf_counter()
        predict_proba_positive(fitted, x)
        durations.append((time.perf_counter() - started) * 1000.0)
    return float(sum(durations) / len(durations))


@dataclass(frozen=True)
class ParetoRow:
    model: str
    pr_auc: float
    roc_auc: float
    brier_score: float
    log_loss: float
    ks_statistic: float
    calibration_slope: float
    split_stability_roc_auc_stdev: float
    max_robustness_pr_auc_degradation: float
    max_subgroup_selection_rate_gap: float | None
    artifact_size_bytes: int
    scoring_latency_ms: float
    explainability_tier: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "pr_auc": round(self.pr_auc, 6),
            "roc_auc": round(self.roc_auc, 6),
            "brier_score": round(self.brier_score, 6),
            "log_loss": round(self.log_loss, 6),
            "ks_statistic": round(self.ks_statistic, 6),
            "calibration_slope": round(self.calibration_slope, 6),
            "split_stability_roc_auc_stdev": round(self.split_stability_roc_auc_stdev, 6),
            "max_robustness_pr_auc_degradation": round(self.max_robustness_pr_auc_degradation, 6),
            "max_subgroup_selection_rate_gap": (
                round(self.max_subgroup_selection_rate_gap, 6)
                if self.max_subgroup_selection_rate_gap is not None
                else None
            ),
            "artifact_size_bytes": self.artifact_size_bytes,
            "scoring_latency_ms": round(self.scoring_latency_ms, 4),
            "explainability_tier": self.explainability_tier,
        }


def build_pareto_comparison(
    *,
    df: pd.DataFrame,
    raw_test: pd.DataFrame,
    y_test: pd.Series,
    candidate_fitted: FittedModel,
    challenger_fitted: FittedModel,
    candidate_artifact_path: Path,
    challenger_artifact_path: Path,
    candidate_test_metrics: dict[str, Any],
    challenger_test_metrics: dict[str, Any],
    candidate_split_stability: dict[str, Any],
    candidate_max_robustness_pr_auc_degradation: float,
    registry: FeatureRegistry,
    contract: TargetContract,
    config: EvaluationConfig,
    threshold: float,
) -> pd.DataFrame:
    x_test = raw_test[[]].copy()
    from credlens.modeling.features import engineer_features

    x_test = engineer_features(raw_test)[FEATURE_COLUMNS]

    challenger_stability = split_stability_sweep(
        df, registry=registry, contract=contract, config=config, model_kind="hist_gradient_boosting"
    )
    challenger_p = predict_proba_positive(challenger_fitted, x_test)
    challenger_robustness = run_robustness_suite(
        challenger_fitted, raw_test, y_test, challenger_p, threshold=threshold, config=config
    )
    challenger_subgroup = run_subgroup_validation(
        raw_test,
        y_test,
        challenger_p,
        threshold=threshold,
        age_buckets=config.subgroup_audit["age_buckets"],
        bootstrap_cfg={"n_resamples": 50, "seed": 20260728, "percentiles": [2.5, 50, 97.5]},
    )
    challenger_max_gap = max(
        (
            g.absolute_gap
            for g in challenger_subgroup.gap_reports
            if g.metric == "selection_rate" and g.absolute_gap is not None
        ),
        default=None,
    )
    candidate_p = predict_proba_positive(candidate_fitted, x_test)
    candidate_subgroup = run_subgroup_validation(
        raw_test,
        y_test,
        candidate_p,
        threshold=threshold,
        age_buckets=config.subgroup_audit["age_buckets"],
        bootstrap_cfg={"n_resamples": 50, "seed": 20260728, "percentiles": [2.5, 50, 97.5]},
    )
    candidate_max_gap = max(
        (
            g.absolute_gap
            for g in candidate_subgroup.gap_reports
            if g.metric == "selection_rate" and g.absolute_gap is not None
        ),
        default=None,
    )

    disc_c, cal_c = candidate_test_metrics["discrimination"], candidate_test_metrics["calibration"]
    disc_h, cal_h = (
        challenger_test_metrics["discrimination"],
        challenger_test_metrics["calibration"],
    )

    rows = [
        ParetoRow(
            model="logistic_regression (candidate)",
            pr_auc=disc_c["pr_auc"],
            roc_auc=disc_c["roc_auc"],
            brier_score=cal_c["brier_score"],
            log_loss=cal_c["log_loss"],
            ks_statistic=disc_c["ks_statistic"],
            calibration_slope=cal_c["calibration_slope"],
            split_stability_roc_auc_stdev=candidate_split_stability["roc_auc_stdev"],
            max_robustness_pr_auc_degradation=candidate_max_robustness_pr_auc_degradation,
            max_subgroup_selection_rate_gap=candidate_max_gap,
            artifact_size_bytes=candidate_artifact_path.stat().st_size,
            scoring_latency_ms=_measure_latency_ms(candidate_fitted, x_test),
            explainability_tier="high (linear coefficients/odds ratios)",
        ),
        ParetoRow(
            model="hist_gradient_boosting (challenger)",
            pr_auc=disc_h["pr_auc"],
            roc_auc=disc_h["roc_auc"],
            brier_score=cal_h["brier_score"],
            log_loss=cal_h["log_loss"],
            ks_statistic=disc_h["ks_statistic"],
            calibration_slope=cal_h["calibration_slope"],
            split_stability_roc_auc_stdev=challenger_stability.roc_auc_stdev,
            max_robustness_pr_auc_degradation=max(
                (r.pr_auc_degradation for r in challenger_robustness if not r.had_error_or_nan),
                default=0.0,
            ),
            max_subgroup_selection_rate_gap=challenger_max_gap,
            artifact_size_bytes=challenger_artifact_path.stat().st_size,
            scoring_latency_ms=_measure_latency_ms(challenger_fitted, x_test),
            explainability_tier="low (non-linear ensemble - permutation importance/PDP only)",
        ),
    ]
    return pd.DataFrame([r.to_dict() for r in rows])
