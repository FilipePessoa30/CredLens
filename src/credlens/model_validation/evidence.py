"""Freezes the evidence an independent validation run is allowed to touch
(Phase 9 section 5) - a snapshot of hashes/IDs/metrics taken BEFORE any
recomputation happens, so every later module compares against a fixed
point instead of silently re-reading (and potentially seeing a changed)
`reports/modeling/` output mid-run.

Freezing does not retrain, retune, recalibrate, or reselect a threshold -
it only reads what Phase 8 already wrote (the experiment record, the
locked test predictions, the split assignment table, the registered
config files) and hashes/copies it. If a correction requires new
training, `credlens.model_validation.challenger_review`/
`reporting.build_reduced_experiment` create a NEW experiment id and this
module freezes THAT experiment separately - `EXP_behavioral_default_v1`
itself is never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import scipy
import sklearn
import yaml

from credlens import __version__ as credlens_version
from credlens.data.checksums import compute_sha256
from credlens.modeling.registry import RegistryError, load_experiment

_VALIDATION_CONFIG_PATH = Path("config/model_validation/validation.yml")

_CONFIG_FILES_HASHED = (
    Path("config/modeling/behavioral_default.yml"),
    Path("config/modeling/feature_registry.yml"),
    Path("config/modeling/evaluation.yml"),
    Path("config/model_validation/validation.yml"),
)

EXPERIMENTS_DIR = Path("reports/modeling/experiments")
TABLES_DIR = Path("reports/modeling/tables")
EVIDENCE_DIR = Path("reports/model_validation/evidence")


class EvidenceError(Exception):
    """Raised when evidence cannot be frozen (missing artifact) or a
    frozen manifest is loaded but no longer matches what is on disk."""


@dataclass(frozen=True)
class ValidationConfig:
    validation_config_version: str
    raw: dict[str, Any]

    @property
    def recomputation(self) -> dict[str, Any]:
        return dict(self.raw["recomputation"])

    @property
    def permutation_test(self) -> dict[str, Any]:
        return dict(self.raw["permutation_test"])

    @property
    def collinearity(self) -> dict[str, Any]:
        return dict(self.raw["collinearity"])

    @property
    def subgroup_bootstrap(self) -> dict[str, Any]:
        return dict(self.raw["subgroup_bootstrap"])

    @property
    def gates(self) -> dict[str, Any]:
        return dict(self.raw["gates"])

    @property
    def pareto_axes(self) -> list[str]:
        return list(self.raw["pareto_axes"])


def load_validation_config(repo_root: Path | None = None) -> ValidationConfig:
    repo_root = repo_root or Path.cwd()
    path = repo_root / _VALIDATION_CONFIG_PATH
    if not path.is_file():
        raise EvidenceError(f"Validation config not found at '{path}'.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ValidationConfig(validation_config_version=raw["validation_config_version"], raw=raw)


def _hash_config_files(repo_root: Path) -> str:
    digests = []
    for rel_path in _CONFIG_FILES_HASHED:
        path = repo_root / rel_path
        if not path.is_file():
            raise EvidenceError(f"Expected config file '{path}' not found while freezing evidence.")
        digests.append(compute_sha256(path))
    return hashlib.sha256("|".join(digests).encode("utf-8")).hexdigest()


def _hash_split_ids(split_assignment_path: Path) -> dict[str, str]:
    """Independent re-hash of the split assignment table, grouped by
    partition - deliberately re-implemented here (sorted id list -> one
    sha256 per partition) rather than importing
    `credlens.modeling.splitting`'s private hashing helper."""
    if not split_assignment_path.is_file():
        raise EvidenceError(f"Split assignment table not found at '{split_assignment_path}'.")
    table = pd.read_csv(split_assignment_path)
    hashes: dict[str, str] = {}
    for split_name in ("train", "validation", "test"):
        ids = sorted(table.loc[table["split"] == split_name, "id"].tolist())
        joined = ",".join(str(i) for i in ids)
        hashes[f"{split_name}_id_hash"] = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return hashes


def _hash_predictions_and_target(predictions_test_path: Path) -> tuple[str, str]:
    if not predictions_test_path.is_file():
        raise EvidenceError(
            f"Locked test predictions not found at '{predictions_test_path}' - "
            "run 'credlens model evaluate' before freezing evidence."
        )
    prediction_hash = compute_sha256(predictions_test_path)
    frame = pd.read_csv(predictions_test_path)[["id", "y_true"]].sort_values("id")
    target_hash = hashlib.sha256(frame.to_csv(index=False).encode("utf-8")).hexdigest()
    return prediction_hash, target_hash


@dataclass(frozen=True)
class EvidenceManifest:
    experiment_id: str
    model_id: str | None
    dataset_id: str
    dataset_hash: str
    split_hash: str
    train_id_hash: str
    validation_id_hash: str
    test_id_hash: str
    feature_registry_version: str
    config_hash: str
    prediction_hash: str
    target_hash: str
    artifact_hash: str | None
    dependency_versions: dict[str, str]
    original_test_metrics: dict[str, Any]
    code_version: str
    frozen_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "model_id": self.model_id,
            "dataset_id": self.dataset_id,
            "dataset_hash": self.dataset_hash,
            "split_hash": self.split_hash,
            "train_id_hash": self.train_id_hash,
            "validation_id_hash": self.validation_id_hash,
            "test_id_hash": self.test_id_hash,
            "feature_registry_version": self.feature_registry_version,
            "config_hash": self.config_hash,
            "prediction_hash": self.prediction_hash,
            "target_hash": self.target_hash,
            "artifact_hash": self.artifact_hash,
            "dependency_versions": self.dependency_versions,
            "original_test_metrics": self.original_test_metrics,
            "code_version": self.code_version,
            "frozen_at_utc": self.frozen_at_utc,
        }


def _validation_dependency_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "credlens": credlens_version,
        "scikit_learn": sklearn.__version__,
        "scipy": scipy.__version__,
        "pandas": pd.__version__,
    }


def freeze_evidence(
    experiment_id: str, model_id: str | None = None, *, repo_root: Path | None = None
) -> EvidenceManifest:
    """The ONLY function in this package allowed to read
    `reports/modeling/` directly for the purpose of establishing a
    baseline - every other `model_validation` module takes an
    `EvidenceManifest` (or re-reads the exact same frozen files) rather
    than reaching into `reports/modeling/` on its own."""
    repo_root = repo_root or Path.cwd()
    try:
        experiment = load_experiment(repo_root / EXPERIMENTS_DIR / f"{experiment_id}.json")
    except RegistryError as exc:
        raise EvidenceError(str(exc)) from exc
    if experiment.status not in ("evaluated", "registered_candidate", "gates_failed"):
        raise EvidenceError(
            f"Experiment '{experiment_id}' has not been evaluated yet (status={experiment.status})."
        )

    split_hashes = _hash_split_ids(
        repo_root / EXPERIMENTS_DIR / experiment_id / "split_assignment.csv"
    )
    prediction_hash, target_hash = _hash_predictions_and_target(
        repo_root / TABLES_DIR / f"{experiment_id}__predictions_test.csv"
    )

    main_test_metrics = experiment.metrics.get("test", {}).get("logistic_regression", {})

    manifest = EvidenceManifest(
        experiment_id=experiment_id,
        model_id=model_id,
        dataset_id=experiment.dataset_id,
        dataset_hash=experiment.dataset_hash,
        split_hash=experiment.split_hash,
        train_id_hash=split_hashes["train_id_hash"],
        validation_id_hash=split_hashes["validation_id_hash"],
        test_id_hash=split_hashes["test_id_hash"],
        feature_registry_version=experiment.feature_registry_version,
        config_hash=_hash_config_files(repo_root),
        prediction_hash=prediction_hash,
        target_hash=target_hash,
        artifact_hash=experiment.artifact_hash,
        dependency_versions=_validation_dependency_versions(),
        original_test_metrics=main_test_metrics,
        code_version=credlens_version,
    )
    return manifest


def write_evidence(manifest: EvidenceManifest, *, repo_root: Path | None = None) -> Path:
    repo_root = repo_root or Path.cwd()
    out_dir = repo_root / EVIDENCE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{manifest.experiment_id}.json"
    path.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_evidence(experiment_id: str, *, repo_root: Path | None = None) -> EvidenceManifest:
    repo_root = repo_root or Path.cwd()
    path = repo_root / EVIDENCE_DIR / f"{experiment_id}.json"
    if not path.is_file():
        raise EvidenceError(
            f"No frozen evidence for '{experiment_id}' at '{path}' - "
            "run 'credlens model validate-independent' first."
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    return EvidenceManifest(**raw)
