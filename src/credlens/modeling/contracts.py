"""Loads and validates the Phase 8 versioned contracts:
`config/modeling/behavioral_default.yml` (target/problem framing),
`config/modeling/feature_registry.yml` (feature governance), and
`config/modeling/evaluation.yml` (protocol configuration).

`validate_target_contract` is the functional test surface Phase 8 section
5 requires: binary target, no nulls, documented domain, prevalence within
tolerance of what the contract declares, no target/ID leaking into a
feature frame, no duplicate IDs, and consistency with the acquired
source's own manifest hash.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml

FeatureStatus = Literal[
    "allowed",
    "engineered_allowed",
    "audit_only",
    "excluded_identifier",
    "excluded_target",
    "excluded_sensitive",
    "excluded_leakage",
    "unsupported",
]

_BEHAVIORAL_DEFAULT_PATH = Path("config/modeling/behavioral_default.yml")
_FEATURE_REGISTRY_PATH = Path("config/modeling/feature_registry.yml")
_EVALUATION_PATH = Path("config/modeling/evaluation.yml")

_PREVALENCE_TOLERANCE = 0.001


class ContractError(Exception):
    """Raised for any target/feature-registry/evaluation-config violation."""


@dataclass(frozen=True)
class TargetContract:
    contract_version: str
    target_column: str
    identifier_column: str
    positive_label: int
    negative_label: int
    expected_prevalence: float
    source_id: str
    acquired_hash_sha256: str
    raw: dict[str, Any]

    @property
    def name_en(self) -> str:
        return str(self.raw["problem_framing"]["name_en"])

    @property
    def name_pt_br(self) -> str:
        return str(self.raw["problem_framing"]["name_pt_br"])

    @property
    def excluded_columns(self) -> list[dict[str, Any]]:
        return list(self.raw.get("excluded_columns", []))


@dataclass(frozen=True)
class FeatureRegistry:
    registry_version: str
    raw: dict[str, Any]

    @property
    def engineered_features(self) -> list[dict[str, Any]]:
        return list(self.raw.get("engineered_features", []))

    @property
    def allowed_feature_names(self) -> list[str]:
        return [
            f["name"]
            for f in self.engineered_features
            if f["status"] in ("allowed", "engineered_allowed")
        ]

    @property
    def audit_only_columns(self) -> list[str]:
        return list(self.raw.get("audit_only_group", []))


@dataclass(frozen=True)
class EvaluationConfig:
    config_version: str
    raw: dict[str, Any]

    @property
    def split(self) -> dict[str, Any]:
        return dict(self.raw["split"])

    @property
    def tuning(self) -> dict[str, Any]:
        return dict(self.raw["tuning"])

    @property
    def calibration(self) -> dict[str, Any]:
        return dict(self.raw["calibration"])

    @property
    def thresholds(self) -> dict[str, Any]:
        return dict(self.raw["thresholds"])

    @property
    def uncertainty(self) -> dict[str, Any]:
        return dict(self.raw["uncertainty"])

    @property
    def robustness(self) -> dict[str, Any]:
        return dict(self.raw["robustness"])

    @property
    def negative_controls(self) -> dict[str, Any]:
        return dict(self.raw["negative_controls"])

    @property
    def subgroup_audit(self) -> dict[str, Any]:
        return dict(self.raw["subgroup_audit"])

    @property
    def gates(self) -> dict[str, Any]:
        return dict(self.raw["gates"])


def load_target_contract(repo_root: Path | None = None) -> TargetContract:
    repo_root = repo_root or Path.cwd()
    path = repo_root / _BEHAVIORAL_DEFAULT_PATH
    if not path.is_file():
        raise ContractError(f"Target contract not found at '{path}'.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    target = raw["target"]
    return TargetContract(
        contract_version=raw["contract_version"],
        target_column=target["column"],
        identifier_column=raw["identifier_column"],
        positive_label=int(target["positive_label"]),
        negative_label=int(target["negative_label"]),
        expected_prevalence=float(target["expected_prevalence"]),
        source_id=raw["source"]["source_id"],
        acquired_hash_sha256=raw["source"]["acquired_hash_sha256"],
        raw=raw,
    )


def load_feature_registry(repo_root: Path | None = None) -> FeatureRegistry:
    repo_root = repo_root or Path.cwd()
    path = repo_root / _FEATURE_REGISTRY_PATH
    if not path.is_file():
        raise ContractError(f"Feature registry not found at '{path}'.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return FeatureRegistry(registry_version=raw["registry_version"], raw=raw)


def load_evaluation_config(repo_root: Path | None = None) -> EvaluationConfig:
    repo_root = repo_root or Path.cwd()
    path = repo_root / _EVALUATION_PATH
    if not path.is_file():
        raise ContractError(f"Evaluation config not found at '{path}'.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return EvaluationConfig(config_version=raw["config_version"], raw=raw)


def validate_target_contract(
    df: pd.DataFrame, contract: TargetContract, *, manifest_hash: str | None = None
) -> None:
    """Raises `ContractError` on the first violation found. Checks, in
    order: target column present, binary, no nulls, matches the declared
    positive/negative labels, prevalence within tolerance of the
    contract's declared value, ID column has no duplicates, target is not
    present among engineered feature names, and (if `manifest_hash` is
    given) the source's acquired hash still matches the contract."""
    if contract.target_column not in df.columns:
        raise ContractError(f"Target column '{contract.target_column}' not found in data.")

    target = df[contract.target_column]
    if target.isna().any():
        raise ContractError(f"Target column '{contract.target_column}' contains null values.")

    observed_labels = set(target.unique().tolist())
    expected_labels = {contract.positive_label, contract.negative_label}
    if not observed_labels <= expected_labels:
        raise ContractError(
            f"Target column contains labels outside {expected_labels}: {observed_labels}."
        )

    prevalence = float(target.mean())
    if abs(prevalence - contract.expected_prevalence) > _PREVALENCE_TOLERANCE:
        raise ContractError(
            f"Observed prevalence {prevalence:.6f} diverges from the contract's declared "
            f"{contract.expected_prevalence:.6f} by more than {_PREVALENCE_TOLERANCE}."
        )

    id_col = contract.identifier_column
    if id_col in df.columns and df[id_col].duplicated().any():
        raise ContractError(f"Identifier column '{id_col}' contains duplicate values.")

    if manifest_hash is not None and manifest_hash.lower() != contract.acquired_hash_sha256.lower():
        raise ContractError(
            f"Manifest hash '{manifest_hash}' no longer matches the contract's recorded "
            f"'{contract.acquired_hash_sha256}' - the acquired source may have changed."
        )


def assert_target_not_in_features(feature_columns: list[str], contract: TargetContract) -> None:
    if contract.target_column in feature_columns:
        raise ContractError(
            f"Target column '{contract.target_column}' must never appear among feature columns."
        )
