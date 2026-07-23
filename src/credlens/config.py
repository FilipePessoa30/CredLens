"""Configuration loading and validation for CredLens.

Foundation phase: reads and validates `config/base.yaml`. The schema is
intentionally small (project metadata, logging, logical paths) and
contains no credentials and no business thresholds. See
docs/architecture.md and config/README.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config/base.yaml")

_VALID_ENVIRONMENTS = {"development", "test", "production"}
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class ConfigError(Exception):
    """Raised when the CredLens configuration cannot be loaded or is invalid."""


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    display_name: str
    environment: str


@dataclass(frozen=True)
class LoggingConfig:
    level: str
    format: str


@dataclass(frozen=True)
class PathsConfig:
    data_dir: str
    config_dir: str
    docs_dir: str


@dataclass(frozen=True)
class Config:
    project: ProjectConfig
    logging: LoggingConfig
    paths: PathsConfig
    source_path: Path


def _require_mapping(value: Any, key: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"Expected section '{key}' to be a mapping, got {type(value).__name__}.")
    return value


def _require_section(data: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in data:
        raise ConfigError(f"Missing required top-level section '{key}'.")
    return _require_mapping(data[key], key)


def _require_str(section: dict[str, Any], key: str, section_name: str) -> str:
    if key not in section:
        raise ConfigError(f"Missing required key '{section_name}.{key}'.")
    value = section[key]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Expected '{section_name}.{key}' to be a non-empty string.")
    return value


def load_config(path: Path | str | None = None) -> Config:
    """Load and validate the CredLens configuration file.

    Args:
        path: path to a YAML config file. Defaults to `config/base.yaml`
            relative to the current working directory.

    Returns:
        A validated, immutable `Config`.

    Raises:
        ConfigError: if the file is missing, unreadable, not valid YAML,
            not a mapping at the top level, or missing/malformed required
            keys.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH

    if not config_path.exists():
        raise ConfigError(
            f"Configuration file not found at '{config_path}'. "
            "Expected a YAML file such as config/base.yaml."
        )
    if not config_path.is_file():
        raise ConfigError(f"Configuration path '{config_path}' is not a file.")

    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Could not read configuration file '{config_path}': {exc}") from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Configuration file '{config_path}' is not valid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(
            f"Configuration file '{config_path}' must contain a top-level mapping, "
            f"got {type(data).__name__}."
        )

    project_raw = _require_section(data, "project")
    logging_raw = _require_section(data, "logging")
    paths_raw = _require_section(data, "paths")

    project = ProjectConfig(
        name=_require_str(project_raw, "name", "project"),
        display_name=_require_str(project_raw, "display_name", "project"),
        environment=_require_str(project_raw, "environment", "project"),
    )
    if project.environment not in _VALID_ENVIRONMENTS:
        raise ConfigError(
            f"Invalid 'project.environment' value '{project.environment}'. "
            f"Expected one of {sorted(_VALID_ENVIRONMENTS)}."
        )

    logging_config = LoggingConfig(
        level=_require_str(logging_raw, "level", "logging"),
        format=_require_str(logging_raw, "format", "logging"),
    )
    if logging_config.level.upper() not in _VALID_LOG_LEVELS:
        raise ConfigError(
            f"Invalid 'logging.level' value '{logging_config.level}'. "
            f"Expected one of {sorted(_VALID_LOG_LEVELS)}."
        )

    paths = PathsConfig(
        data_dir=_require_str(paths_raw, "data_dir", "paths"),
        config_dir=_require_str(paths_raw, "config_dir", "paths"),
        docs_dir=_require_str(paths_raw, "docs_dir", "paths"),
    )

    return Config(project=project, logging=logging_config, paths=paths, source_path=config_path)
