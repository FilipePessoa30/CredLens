"""Loads the Phase 9 monitoring configuration files
(`config/monitoring/reference.yml`, `thresholds.yml`, `scenarios.yml`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_REFERENCE_PATH = Path("config/monitoring/reference.yml")
_THRESHOLDS_PATH = Path("config/monitoring/thresholds.yml")
_SCENARIOS_PATH = Path("config/monitoring/scenarios.yml")
_SCENARIOS_REGISTRY_PATH = Path("config/monitoring/scenarios_registry.yml")


class MonitoringConfigError(Exception):
    """Raised when a monitoring config file is missing or malformed."""


@dataclass(frozen=True)
class ReferenceConfig:
    reference_config_version: str
    raw: dict[str, Any]

    @property
    def feature_distribution(self) -> dict[str, Any]:
        return dict(self.raw["feature_distribution"])

    @property
    def score_distribution(self) -> dict[str, Any]:
        return dict(self.raw["score_distribution"])

    @property
    def bootstrap(self) -> dict[str, Any]:
        return dict(self.raw["bootstrap"])


@dataclass(frozen=True)
class ThresholdsConfig:
    thresholds_config_version: str
    raw: dict[str, Any]

    @property
    def states(self) -> list[str]:
        return list(self.raw["states"])

    @property
    def calibration(self) -> dict[str, Any]:
        return dict(self.raw["calibration"])

    @property
    def metric_families(self) -> dict[str, Any]:
        return dict(self.raw["metric_families"])

    @property
    def multiple_comparisons(self) -> dict[str, Any]:
        return dict(self.raw["multiple_comparisons"])

    @property
    def calibration_study(self) -> dict[str, Any]:
        return dict(self.raw["calibration_study"])

    @property
    def demonstrative_targets(self) -> dict[str, Any]:
        return dict(self.raw["demonstrative_targets"])

    @property
    def data_quality_fixed_thresholds(self) -> dict[str, Any]:
        return dict(self.raw["data_quality_fixed_thresholds"])

    @property
    def target_distribution_drift_calibration(self) -> dict[str, Any]:
        return dict(self.raw["target_distribution_drift_calibration"])

    @property
    def subgroup_composition_drift_calibration(self) -> dict[str, Any]:
        return dict(self.raw["subgroup_composition_drift_calibration"])


@dataclass(frozen=True)
class ScenariosConfig:
    scenarios_config_version: str
    raw: dict[str, Any]

    @property
    def batch_size(self) -> int:
        return int(self.raw["batch_size"])

    @property
    def seed(self) -> int:
        return int(self.raw["seed"])

    @property
    def batches(self) -> list[dict[str, Any]]:
        return list(self.raw["batches"])


def _load_yaml(repo_root: Path, rel_path: Path) -> dict[str, Any]:
    path = repo_root / rel_path
    if not path.is_file():
        raise MonitoringConfigError(f"Monitoring config not found at '{path}'.")
    result: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return result


def load_reference_config(repo_root: Path | None = None) -> ReferenceConfig:
    repo_root = repo_root or Path.cwd()
    raw = _load_yaml(repo_root, _REFERENCE_PATH)
    return ReferenceConfig(reference_config_version=raw["reference_config_version"], raw=raw)


def load_thresholds_config(repo_root: Path | None = None) -> ThresholdsConfig:
    repo_root = repo_root or Path.cwd()
    raw = _load_yaml(repo_root, _THRESHOLDS_PATH)
    return ThresholdsConfig(thresholds_config_version=raw["thresholds_config_version"], raw=raw)


def load_scenarios_config(repo_root: Path | None = None) -> ScenariosConfig:
    repo_root = repo_root or Path.cwd()
    raw = _load_yaml(repo_root, _SCENARIOS_PATH)
    return ScenariosConfig(scenarios_config_version=raw["scenarios_config_version"], raw=raw)


def load_scenario_registry(repo_root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Phase 10B - the documented, versioned per-scenario expectation
    registry (`config/monitoring/scenarios_registry.yml`):
    `credlens.monitoring.detection_eval.EXPECTED_OUTCOMES` must always
    agree with this file (enforced by
    `tests/test_monitoring_calibration_incidents_detection.py`'s
    consistency test) - this is the single documented source of truth a
    reviewer reads, `EXPECTED_OUTCOMES` is the executable copy the
    detection-evaluation code actually runs against."""
    repo_root = repo_root or Path.cwd()
    raw = _load_yaml(repo_root, _SCENARIOS_REGISTRY_PATH)
    scenarios: dict[str, dict[str, Any]] = dict(raw["scenarios"])
    return scenarios
