"""Experiment registry, model candidate registry, and promotion gates
(Phase 8 sections 17, 24, 25).

An experiment is registered every time the full pipeline runs - compact,
versioned, JSON, no external service. A model only becomes a `candidate`
(NEVER `production`, NEVER auto-promoted to `champion`) if every gate in
`evaluate_gates` passes; `run_official_experiment` in
`credlens.modeling.reporting` is the only caller that decides whether to
call `register_model_candidate` at all - a failed gate set means
"No model eligible for registration" is a real, legitimate outcome, not
an error.

Serialization uses `joblib` (ships with scikit-learn). This is still
pickle-based - `load_model_candidate` never loads a candidate without
first re-verifying its SHA-256 against the manifest, and this project
never loads a `.joblib` file it did not itself produce.
"""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import scipy
import sklearn

from credlens import __version__ as credlens_version
from credlens.data.checksums import compute_sha256
from credlens.modeling.contracts import EvaluationConfig
from credlens.modeling.features import FEATURE_COLUMNS
from credlens.modeling.training import FittedModel

CANDIDATE_STATUS = "candidate"  # NEVER "production", NEVER auto-promoted to "champion"


class RegistryError(Exception):
    """Raised for experiment/model registry read/write/validation failures."""


def dependency_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "credlens": credlens_version,
        "scikit_learn": sklearn.__version__,
        "scipy": scipy.__version__,
        "pandas": pd.__version__,
        "numpy": np.__version__,
    }


@dataclass(frozen=True)
class Experiment:
    experiment_id: str
    dataset_id: str
    dataset_hash: str
    split_hash: str
    target_column: str
    feature_set: list[str]
    feature_registry_version: str
    preprocessing: str
    estimator: str
    hyperparameters: dict[str, Any]
    seed: int
    cv_description: str
    metrics: dict[str, Any]
    calibration: dict[str, Any]
    threshold_policy: str
    subgroup_audit_summary: dict[str, Any]
    robustness_summary: dict[str, Any]
    artifact_hash: str | None
    dependency_versions: dict[str, str]
    status: str
    warnings: list[str] = field(default_factory=list)
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "dataset_id": self.dataset_id,
            "dataset_hash": self.dataset_hash,
            "split_hash": self.split_hash,
            "target_column": self.target_column,
            "feature_set": self.feature_set,
            "feature_registry_version": self.feature_registry_version,
            "preprocessing": self.preprocessing,
            "estimator": self.estimator,
            "hyperparameters": self.hyperparameters,
            "seed": self.seed,
            "cv_description": self.cv_description,
            "metrics": self.metrics,
            "calibration": self.calibration,
            "threshold_policy": self.threshold_policy,
            "subgroup_audit_summary": self.subgroup_audit_summary,
            "robustness_summary": self.robustness_summary,
            "artifact_hash": self.artifact_hash,
            "dependency_versions": self.dependency_versions,
            "status": self.status,
            "warnings": self.warnings,
            "created_at_utc": self.created_at_utc,
        }


def write_experiment(experiment: Experiment, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{experiment.experiment_id}.json"
    path.write_text(json.dumps(experiment.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_experiment(path: Path) -> Experiment:
    if not path.is_file():
        raise RegistryError(f"Experiment file not found at '{path}'.")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Experiment(**raw)


def list_experiments(output_dir: Path) -> list[str]:
    if not output_dir.is_dir():
        return []
    return sorted(p.stem for p in output_dir.glob("*.json"))


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class GateReport:
    gates: list[GateResult]
    eligible: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gates": [g.to_dict() for g in self.gates],
            "eligible": self.eligible,
            "reason": self.reason,
        }


def evaluate_gates(
    *,
    dummy_pr_auc: float,
    simple_rule_pr_auc: float,
    candidate_pr_auc: float,
    candidate_roc_auc: float,
    no_leakage_detected: bool,
    calibration_acceptable: bool,
    split_stability_roc_auc_stdev: float,
    subgroup_audit_completed: bool,
    artifact_validated: bool,
    config: EvaluationConfig,
) -> GateReport:
    """Every gate must pass for `eligible=True`. AUC alone never decides
    eligibility (Phase 8 section 17: "A seleção não pode usar somente
    AUC") - beating both baselines, a clean leakage audit, acceptable
    calibration, cross-seed stability, a completed subgroup audit, and
    artifact validation are all independently checked."""
    gates_cfg = config.gates
    gates = [
        GateResult(
            "beats_dummy_baseline_pr_auc",
            (candidate_pr_auc - dummy_pr_auc) >= float(gates_cfg["min_pr_auc_uplift_over_dummy"]),
            f"candidate PR-AUC {candidate_pr_auc:.4f} vs. dummy {dummy_pr_auc:.4f}",
        ),
        GateResult(
            "beats_simple_rule_baseline_pr_auc",
            (candidate_pr_auc - simple_rule_pr_auc)
            >= float(gates_cfg["min_pr_auc_uplift_over_simple_rule"]),
            f"candidate PR-AUC {candidate_pr_auc:.4f} vs. simple rule {simple_rule_pr_auc:.4f}",
        ),
        GateResult(
            "meets_minimum_test_roc_auc",
            candidate_roc_auc >= float(gates_cfg["min_test_roc_auc"]),
            f"candidate ROC-AUC {candidate_roc_auc:.4f} vs. minimum "
            f"{gates_cfg['min_test_roc_auc']}",
        ),
        GateResult("no_leakage_detected", no_leakage_detected, "static + negative-control checks"),
        GateResult(
            "calibration_acceptable", calibration_acceptable, "calibration comparison completed"
        ),
        GateResult(
            "stable_across_split_seeds",
            split_stability_roc_auc_stdev <= float(gates_cfg["max_split_stability_roc_auc_stdev"]),
            f"ROC-AUC stdev across seeds {split_stability_roc_auc_stdev:.4f} vs. max "
            f"{gates_cfg['max_split_stability_roc_auc_stdev']}",
        ),
        GateResult(
            "subgroup_audit_completed", subgroup_audit_completed, "post-hoc subgroup audit ran"
        ),
        GateResult("artifact_validated", artifact_validated, "input/output schema validation"),
    ]
    eligible = all(g.passed for g in gates)
    reason = (
        "All gates passed - eligible for candidate registration."
        if eligible
        else "One or more gates failed - No model eligible for registration."
    )
    return GateReport(gates=gates, eligible=eligible, reason=reason)


@dataclass(frozen=True)
class ModelCandidateManifest:
    model_id: str
    status: str
    experiment_id: str
    artifact_relative_path: str
    artifact_sha256: str
    input_schema: dict[str, str]
    output_schema: dict[str, str]
    benchmark_source_id: str
    feature_registry_version: str
    test_metrics: dict[str, Any]
    limitations: list[str]
    risk_band_cuts: list[float]
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "status": self.status,
            "experiment_id": self.experiment_id,
            "artifact_relative_path": self.artifact_relative_path,
            "artifact_sha256": self.artifact_sha256,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "benchmark_source_id": self.benchmark_source_id,
            "feature_registry_version": self.feature_registry_version,
            "test_metrics": self.test_metrics,
            "limitations": self.limitations,
            "risk_band_cuts": self.risk_band_cuts,
            "created_at_utc": self.created_at_utc,
        }


_OUTPUT_SCHEMA = {
    "pseudonymous_record_id": "string",
    "predicted_default_probability": "float64",
    "risk_band": "string",
    "model_version": "string",
    "scoring_timestamp": "string",
    "input_schema_version": "string",
}


def register_model_candidate(
    fitted: FittedModel,
    *,
    model_id: str,
    experiment_id: str,
    output_dir: Path,
    feature_registry_version: str,
    test_metrics: dict[str, Any],
    limitations: list[str],
    risk_band_cuts: list[float],
    benchmark_source_id: str = "uci-default-credit",
) -> ModelCandidateManifest:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_filename = f"{model_id}.joblib"
    artifact_path = output_dir / artifact_filename
    joblib.dump(fitted.pipeline, artifact_path)
    artifact_hash = compute_sha256(artifact_path)

    manifest = ModelCandidateManifest(
        model_id=model_id,
        status=CANDIDATE_STATUS,
        experiment_id=experiment_id,
        artifact_relative_path=artifact_filename,
        artifact_sha256=artifact_hash,
        input_schema=dict.fromkeys(fitted.feature_columns, "float64"),
        output_schema=dict(_OUTPUT_SCHEMA),
        benchmark_source_id=benchmark_source_id,
        feature_registry_version=feature_registry_version,
        test_metrics=test_metrics,
        limitations=limitations,
        risk_band_cuts=risk_band_cuts,
    )
    manifest_path = output_dir / f"{model_id}.manifest.json"
    # NOT sort_keys=True - input_schema's key ORDER is meaningful (it is
    # the feature order the pipeline was fit on); alphabetizing it would
    # silently desynchronize the written file from FEATURE_COLUMNS even
    # though scoring code no longer trusts this order for correctness.
    manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
    return manifest


def load_model_candidate_manifest(model_id: str, output_dir: Path) -> ModelCandidateManifest:
    manifest_path = output_dir / f"{model_id}.manifest.json"
    if not manifest_path.is_file():
        raise RegistryError(
            f"No model candidate manifest found for '{model_id}' in '{output_dir}'."
        )
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    return ModelCandidateManifest(**raw)


def load_model_candidate(model_id: str, output_dir: Path) -> tuple[Any, ModelCandidateManifest]:
    """Verifies the artifact's hash against the manifest BEFORE calling
    `joblib.load` - refuses to deserialize a tampered/corrupted artifact."""
    manifest = load_model_candidate_manifest(model_id, output_dir)
    artifact_path = output_dir / manifest.artifact_relative_path
    if not artifact_path.is_file():
        raise RegistryError(f"Model artifact not found at '{artifact_path}'.")
    actual_hash = compute_sha256(artifact_path)
    if actual_hash.lower() != manifest.artifact_sha256.lower():
        raise RegistryError(
            f"Artifact hash mismatch for '{model_id}': manifest says "
            f"{manifest.artifact_sha256}, file is actually {actual_hash}. Refusing to load."
        )
    pipeline = joblib.load(artifact_path)
    return pipeline, manifest


def validate_model_candidate(model_id: str, output_dir: Path) -> bool:
    """Loads the candidate (hash-verified) and confirms it can score a
    single synthetic row shaped like its declared input schema, producing
    a value in `[0, 1]` - the "artifact validation" gate.

    Column ORDER always comes from `FEATURE_COLUMNS`, never from
    `manifest.input_schema`'s dict-key iteration order - the manifest is
    JSON, and a `json.dumps(..., sort_keys=True)` write (or any other
    round-trip) would silently reorder it relative to what the pipeline
    was actually fit on, producing a scikit-learn "feature names must
    match" error at scoring time instead of a clear validation failure
    here."""
    pipeline, manifest = load_model_candidate(model_id, output_dir)
    missing = [c for c in FEATURE_COLUMNS if c not in manifest.input_schema]
    if missing:
        raise RegistryError(f"Model candidate '{model_id}' input schema is missing: {missing}")
    probe = pd.DataFrame([dict.fromkeys(FEATURE_COLUMNS, 0.0)])
    proba = pipeline.predict_proba(probe)[:, 1]
    return bool(len(proba) == 1 and 0.0 <= proba[0] <= 1.0)


_RISK_BAND_NAMES = ("low", "medium", "high", "very_high")


def _risk_band(probability: float, cuts: list[float]) -> str:
    for cut, name in zip(cuts, _RISK_BAND_NAMES[:-1], strict=True):
        if probability <= cut:
            return name
    return _RISK_BAND_NAMES[-1]


def score_batch(
    pipeline: Any, manifest: ModelCandidateManifest, input_df: pd.DataFrame
) -> pd.DataFrame:
    """Batch scoring ONLY (Phase 8 section 26) - never an approve/reject
    decision, never a recommended limit/price/rate, never an explanation
    that touches a sensitive attribute. `input_df` must already be
    engineered-feature-shaped (`credlens.modeling.features.
    engineer_features` output) and MUST carry a `pseudonymous_record_id`
    column - this function refuses to invent one from a raw identifier."""
    if "pseudonymous_record_id" not in input_df.columns:
        raise RegistryError("input_df must already contain a 'pseudonymous_record_id' column.")
    missing = [c for c in FEATURE_COLUMNS if c not in input_df.columns]
    if missing:
        raise RegistryError(f"input_df is missing required feature column(s): {missing}")

    probabilities = pipeline.predict_proba(input_df[FEATURE_COLUMNS])[:, 1]
    scored_at = datetime.now(UTC).isoformat()
    return pd.DataFrame(
        {
            "pseudonymous_record_id": input_df["pseudonymous_record_id"].to_numpy(),
            "predicted_default_probability": probabilities,
            "risk_band": [_risk_band(float(p), manifest.risk_band_cuts) for p in probabilities],
            "model_version": manifest.model_id,
            "scoring_timestamp": scored_at,
            "input_schema_version": manifest.feature_registry_version,
        }
    )
