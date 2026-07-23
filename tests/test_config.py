"""Tests for credlens.config: loading and validating config/base.yaml."""

from __future__ import annotations

from pathlib import Path

import pytest

from credlens.config import ConfigError, load_config

VALID_YAML = """
project:
  name: credlens
  display_name: "CredLens - Credit Risk & Portfolio Analytics"
  environment: development
logging:
  level: INFO
  format: "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
paths:
  data_dir: data
  config_dir: config
  docs_dir: docs
"""


def test_load_config_reads_the_repository_base_config() -> None:
    config = load_config()

    assert config.project.name == "credlens"
    assert config.project.environment in {"development", "test", "production"}
    assert config.logging.level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    assert config.paths.data_dir == "data"
    assert config.source_path == Path("config/base.yaml")


def test_load_config_accepts_a_valid_explicit_file(tmp_path: Path) -> None:
    config_file = tmp_path / "custom.yaml"
    config_file.write_text(VALID_YAML, encoding="utf-8")

    config = load_config(config_file)

    assert config.project.name == "credlens"
    assert config.source_path == config_file


def test_load_config_missing_file_raises_config_error(tmp_path: Path) -> None:
    missing_path = tmp_path / "does_not_exist.yaml"

    with pytest.raises(ConfigError, match="not found"):
        load_config(missing_path)


def test_load_config_unreadable_file_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = tmp_path / "unreadable.yaml"
    config_file.write_text(VALID_YAML, encoding="utf-8")

    def _raise_os_error(self: Path, encoding: str | None = None) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", _raise_os_error)

    with pytest.raises(ConfigError, match="Could not read configuration file"):
        load_config(config_file)


def test_load_config_directory_instead_of_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not a file"):
        load_config(tmp_path)


def test_load_config_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    config_file = tmp_path / "broken.yaml"
    config_file.write_text("project: [unclosed", encoding="utf-8")

    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(config_file)


def test_load_config_non_mapping_top_level_raises_config_error(tmp_path: Path) -> None:
    config_file = tmp_path / "list.yaml"
    config_file.write_text("- one\n- two\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="top-level mapping"):
        load_config(config_file)


def test_load_config_missing_section_raises_config_error(tmp_path: Path) -> None:
    config_file = tmp_path / "missing_section.yaml"
    config_file.write_text(
        "project:\n  name: credlens\n  display_name: CredLens\n  environment: development\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Missing required top-level section 'logging'"):
        load_config(config_file)


def test_load_config_section_not_a_mapping_raises_config_error(tmp_path: Path) -> None:
    config_file = tmp_path / "section_not_mapping.yaml"
    config_file.write_text(
        "project: not-a-mapping\n"
        "logging:\n"
        "  level: INFO\n"
        "  format: fmt\n"
        "paths:\n"
        "  data_dir: data\n"
        "  config_dir: config\n"
        "  docs_dir: docs\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Expected section 'project' to be a mapping"):
        load_config(config_file)


def test_load_config_missing_key_within_section_raises_config_error(tmp_path: Path) -> None:
    config_file = tmp_path / "missing_key.yaml"
    config_file.write_text(
        "project:\n"
        "  name: credlens\n"
        "  display_name: CredLens\n"
        "logging:\n"
        "  level: INFO\n"
        "  format: fmt\n"
        "paths:\n"
        "  data_dir: data\n"
        "  config_dir: config\n"
        "  docs_dir: docs\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=r"Missing required key 'project\.environment'"):
        load_config(config_file)


def test_load_config_invalid_environment_raises_config_error(tmp_path: Path) -> None:
    config_file = tmp_path / "bad_env.yaml"
    config_file.write_text(
        VALID_YAML.replace("environment: development", "environment: staging-ish"),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=r"Invalid 'project\.environment'"):
        load_config(config_file)


def test_load_config_invalid_log_level_raises_config_error(tmp_path: Path) -> None:
    config_file = tmp_path / "bad_level.yaml"
    config_file.write_text(
        VALID_YAML.replace("level: INFO", "level: VERBOSE"),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=r"Invalid 'logging\.level'"):
        load_config(config_file)


def test_load_config_empty_string_field_raises_config_error(tmp_path: Path) -> None:
    config_file = tmp_path / "empty_field.yaml"
    config_file.write_text(
        VALID_YAML.replace("name: credlens", 'name: ""'),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="non-empty string"):
        load_config(config_file)
