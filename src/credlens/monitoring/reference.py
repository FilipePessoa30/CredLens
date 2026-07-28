"""Builds the monitoring reference (Phase 9 section 13) - EVERY statistic
here comes from train+validation only, never the locked test set (which
stays reserved for the batches built in `credlens.monitoring.batches`,
themselves scored read-only against an already-frozen model, never used
to re-tune anything).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from credlens.data.checksums import compute_sha256
from credlens.modeling.contracts import load_target_contract
from credlens.modeling.features import FEATURE_COLUMNS, engineer_features
from credlens.modeling.registry import load_model_candidate, load_model_candidate_manifest
from credlens.modeling.splitting import apply_split_assignment_table, load_split_assignment_table

REFERENCE_DIR = Path("reports/monitoring/reference")
MODELS_DIR = Path("reports/modeling/models")
EXPERIMENTS_DIR = Path("reports/modeling/experiments")

_SEX_LABELS = {1: "male", 2: "female"}
_EDUCATION_LABELS = {1: "graduate_school", 2: "university", 3: "high_school", 4: "others"}
_MARRIAGE_LABELS = {1: "married", 2: "single", 3: "others"}
_UNDOCUMENTED = "undocumented_code"


class ReferenceError(Exception):
    """Raised when a monitoring reference cannot be built or loaded."""


def _histogram(values: np.ndarray, bins: int) -> dict[str, list[float]]:
    counts, edges = np.histogram(values, bins=bins)
    return {"bin_edges": [float(e) for e in edges], "counts": [int(c) for c in counts]}


def _feature_stats(values: pd.Series, quantiles: list[float], bins: int) -> dict[str, Any]:
    arr = values.to_numpy(dtype=float)
    return {
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "std": float(arr.std(ddof=0)),
        "min": float(arr.min()),
        "max": float(arr.max()),
        "missingness": float(np.isnan(arr).mean()),
        "quantiles": {str(q): float(np.quantile(arr, q)) for q in quantiles},
        "histogram": _histogram(arr, bins),
    }


@dataclass(frozen=True)
class MonitoringReference:
    reference_id: str
    model_id: str
    experiment_id: str
    dataset_hash: str
    feature_registry_version: str
    artifact_hash: str
    n_reference_rows: int
    feature_stats: dict[str, Any]
    score_stats: dict[str, Any]
    risk_band_distribution: dict[str, float]
    subgroup_composition: dict[str, dict[str, int]]
    created_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "model_id": self.model_id,
            "experiment_id": self.experiment_id,
            "dataset_hash": self.dataset_hash,
            "feature_registry_version": self.feature_registry_version,
            "artifact_hash": self.artifact_hash,
            "n_reference_rows": self.n_reference_rows,
            "feature_stats": self.feature_stats,
            "score_stats": self.score_stats,
            "risk_band_distribution": self.risk_band_distribution,
            "subgroup_composition": self.subgroup_composition,
            "created_at_utc": self.created_at_utc,
        }


def _risk_band(probability: float, cuts: list[float]) -> str:
    names = ("low", "medium", "high", "very_high")
    for cut, name in zip(cuts, names[:-1], strict=True):
        if probability <= cut:
            return name
    return names[-1]


def build_reference(
    model_id: str, *, repo_root: Path | None = None, reference_config: Any = None
) -> tuple[MonitoringReference, pd.DataFrame]:
    """Returns the compact `MonitoringReference` AND the full train+
    validation population DataFrame (id, engineered features, score,
    raw sensitive columns) - the caller writes the former to JSON and the
    latter to a companion CSV used later for bootstrap threshold
    calibration (`credlens.monitoring.thresholds.calibrate_thresholds`)."""
    repo_root = repo_root or Path.cwd()
    from credlens.monitoring.contracts import load_reference_config

    reference_config = reference_config or load_reference_config(repo_root)

    manifest = load_model_candidate_manifest(model_id, repo_root / MODELS_DIR)
    pipeline, manifest = load_model_candidate(model_id, repo_root / MODELS_DIR)
    experiment_id = manifest.experiment_id
    contract = load_target_contract(repo_root)

    from credlens.modeling.data import load_uci_default_credit

    df = load_uci_default_credit(repo_root)
    split_table = load_split_assignment_table(
        repo_root / EXPERIMENTS_DIR / experiment_id / "split_assignment.csv"
    )
    assignment = apply_split_assignment_table(df, split_table, id_column=contract.identifier_column)
    reference_index = assignment.train_index.union(assignment.validation_index)

    features = engineer_features(df)
    x_reference = features.loc[reference_index, FEATURE_COLUMNS]
    scores = pipeline.predict_proba(x_reference)[:, 1]

    quantiles = list(reference_config.feature_distribution["quantiles"])
    bins = int(reference_config.feature_distribution["histogram_bins"])
    feature_stats = {
        col: _feature_stats(x_reference[col], quantiles, bins) for col in FEATURE_COLUMNS
    }

    score_quantiles = list(reference_config.score_distribution["quantiles"])
    score_bins = int(reference_config.score_distribution["histogram_bins"])
    score_stats = _feature_stats(pd.Series(scores), score_quantiles, score_bins)

    bands = [_risk_band(float(p), manifest.risk_band_cuts) for p in scores]
    band_counts = pd.Series(bands).value_counts(normalize=True)
    risk_band_distribution = {str(k): float(v) for k, v in band_counts.items()}

    raw_reference = df.loc[reference_index]
    raw_subgroup_composition: dict[str, Any] = {
        "sex": raw_reference["X2"].map(_SEX_LABELS).fillna(_UNDOCUMENTED).value_counts().to_dict(),
        "education": raw_reference["X3"]
        .map(_EDUCATION_LABELS)
        .fillna(_UNDOCUMENTED)
        .value_counts()
        .to_dict(),
        "marriage": raw_reference["X4"]
        .map(_MARRIAGE_LABELS)
        .fillna(_UNDOCUMENTED)
        .value_counts()
        .to_dict(),
    }
    subgroup_composition: dict[str, dict[str, int]] = {
        k: {str(g): int(c) for g, c in v.items()} for k, v in raw_subgroup_composition.items()
    }

    reference_id = f"REF_{model_id}"
    manifest_hash = manifest.artifact_sha256

    reference = MonitoringReference(
        reference_id=reference_id,
        model_id=model_id,
        experiment_id=experiment_id,
        dataset_hash=compute_sha256(repo_root / MODELS_DIR / f"{model_id}.manifest.json"),
        feature_registry_version=manifest.feature_registry_version,
        artifact_hash=manifest_hash,
        n_reference_rows=len(x_reference),
        feature_stats=feature_stats,
        score_stats=score_stats,
        risk_band_distribution=risk_band_distribution,
        subgroup_composition=subgroup_composition,
        created_at_utc=datetime.now(UTC).isoformat(),
    )

    population = x_reference.copy()
    population.insert(0, "id", df.loc[reference_index, contract.identifier_column].to_numpy())
    population["score"] = scores
    population["y_true"] = df.loc[reference_index, contract.target_column].to_numpy()
    population["sex"] = raw_reference["X2"].map(_SEX_LABELS).fillna(_UNDOCUMENTED).to_numpy()
    population["education"] = (
        raw_reference["X3"].map(_EDUCATION_LABELS).fillna(_UNDOCUMENTED).to_numpy()
    )
    population["marriage"] = (
        raw_reference["X4"].map(_MARRIAGE_LABELS).fillna(_UNDOCUMENTED).to_numpy()
    )

    return reference, population


def write_reference(
    reference: MonitoringReference, population: pd.DataFrame, *, repo_root: Path | None = None
) -> tuple[Path, Path]:
    repo_root = repo_root or Path.cwd()
    out_dir = repo_root / REFERENCE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{reference.reference_id}.json"
    if json_path.is_file():
        raise ReferenceError(
            f"A reference already exists at '{json_path}' - use a different --model-id or remove "
            "the existing reference before rebuilding it."
        )
    json_path.write_text(json.dumps(reference.to_dict(), indent=2), encoding="utf-8")
    population_path = out_dir / f"{reference.reference_id}__population.csv"
    population.to_csv(population_path, index=False)
    return json_path, population_path


def load_reference(reference_id: str, *, repo_root: Path | None = None) -> MonitoringReference:
    repo_root = repo_root or Path.cwd()
    path = repo_root / REFERENCE_DIR / f"{reference_id}.json"
    if not path.is_file():
        raise ReferenceError(f"No monitoring reference found at '{path}'.")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return MonitoringReference(**raw)


def load_reference_population(reference_id: str, *, repo_root: Path | None = None) -> pd.DataFrame:
    repo_root = repo_root or Path.cwd()
    path = repo_root / REFERENCE_DIR / f"{reference_id}__population.csv"
    if not path.is_file():
        raise ReferenceError(f"No reference population table found at '{path}'.")
    return pd.read_csv(path)
