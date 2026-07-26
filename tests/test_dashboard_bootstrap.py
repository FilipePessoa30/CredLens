"""Tests for credlens.dashboard.bootstrap (Phase 7 section 19): CLI args
take priority over environment variables, which take priority over
auto-detection - and auto-detection refuses to guess when the outcome is
ambiguous (both a demo package and a build available) or absent (neither)."""

from __future__ import annotations

from pathlib import Path

import pytest

from credlens.dashboard.bootstrap import (
    ENV_BUILD_ID,
    ENV_DEMO,
    ENV_DEMO_DIR,
    BootstrapError,
    _config_from_auto_detect,
    _config_from_environment,
    _parse_argv,
    demo_package_summary,
    load_validated_dashboard_data,
    resolve_dashboard_config,
)
from credlens.dashboard.config import DashboardConfigError


class TestParseArgv:
    def test_parses_build_id(self) -> None:
        build_id, demo, demo_dir = _parse_argv(["--build-id", "BUILD_x"])
        assert build_id == "BUILD_x"
        assert demo is False
        assert demo_dir is None

    def test_parses_demo_flag(self) -> None:
        build_id, demo, _demo_dir = _parse_argv(["--demo"])
        assert build_id is None
        assert demo is True

    def test_parses_demo_data_dir(self) -> None:
        _build_id, _demo, demo_dir = _parse_argv(["--demo", "--demo-data-dir", "/tmp/x"])
        assert demo_dir == "/tmp/x"

    def test_empty_argv_returns_all_none(self) -> None:
        build_id, demo, demo_dir = _parse_argv([])
        assert build_id is None
        assert demo is False
        assert demo_dir is None

    def test_unknown_extra_args_are_ignored(self) -> None:
        # Streamlit itself may pass its own extra args through - parse_known_args
        # must not choke on them.
        build_id, _demo, _dir = _parse_argv(["--build-id", "X", "--server.port", "8501"])
        assert build_id == "X"


class TestConfigFromEnvironment:
    def test_returns_none_when_neither_env_var_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_BUILD_ID, raising=False)
        monkeypatch.delenv(ENV_DEMO, raising=False)
        assert _config_from_environment() is None

    def test_build_id_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_BUILD_ID, "BUILD_from_env")
        monkeypatch.delenv(ENV_DEMO, raising=False)
        config = _config_from_environment()
        assert config is not None
        assert config.mode == "warehouse"
        assert config.build_id == "BUILD_from_env"

    def test_demo_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_DEMO, "1")
        monkeypatch.delenv(ENV_BUILD_ID, raising=False)
        config = _config_from_environment()
        assert config is not None
        assert config.mode == "demo"

    def test_demo_dir_env_var_is_applied(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(ENV_DEMO, "1")
        monkeypatch.setenv(ENV_DEMO_DIR, str(tmp_path))
        monkeypatch.delenv(ENV_BUILD_ID, raising=False)
        config = _config_from_environment()
        assert config is not None
        assert config.demo_data_dir == tmp_path


class TestConfigFromAutoDetect:
    def test_only_demo_available(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        demo_dir = tmp_path / "dashboard" / "demo_data"
        demo_dir.mkdir(parents=True)
        (demo_dir / "manifest.json").write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        config = _config_from_auto_detect()
        assert config.mode == "demo"

    def test_single_build_available(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "credlens.dashboard.bootstrap.list_available_builds", lambda: ["BUILD_only"]
        )
        config = _config_from_auto_detect()
        assert config.mode == "warehouse"
        assert config.build_id == "BUILD_only"

    def test_multiple_builds_and_no_demo_is_ambiguous(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "credlens.dashboard.bootstrap.list_available_builds", lambda: ["A", "B"]
        )
        with pytest.raises(BootstrapError, match="Multiple builds"):
            _config_from_auto_detect()

    def test_both_demo_and_builds_available_is_ambiguous(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        demo_dir = tmp_path / "dashboard" / "demo_data"
        demo_dir.mkdir(parents=True)
        (demo_dir / "manifest.json").write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("credlens.dashboard.bootstrap.list_available_builds", lambda: ["A"])
        with pytest.raises(BootstrapError, match="Both a demo package"):
            _config_from_auto_detect()

    def test_neither_available_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("credlens.dashboard.bootstrap.list_available_builds", lambda: [])
        with pytest.raises(BootstrapError, match="No warehouse build"):
            _config_from_auto_detect()


class TestResolveDashboardConfigPriority:
    def test_argv_takes_priority_over_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_DEMO, "1")
        config = resolve_dashboard_config(["--build-id", "BUILD_from_argv"])
        assert config.mode == "warehouse"
        assert config.build_id == "BUILD_from_argv"

    def test_environment_used_when_argv_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_BUILD_ID, "BUILD_from_env")
        monkeypatch.delenv(ENV_DEMO, raising=False)
        config = resolve_dashboard_config([])
        assert config.build_id == "BUILD_from_env"

    def test_falls_back_to_auto_detect_when_nothing_given(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv(ENV_BUILD_ID, raising=False)
        monkeypatch.delenv(ENV_DEMO, raising=False)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("credlens.dashboard.bootstrap.list_available_builds", lambda: ["ONLY"])
        config = resolve_dashboard_config([])
        assert config.build_id == "ONLY"


class TestLoadValidatedDashboardDataWrapsErrors:
    def test_config_error_becomes_bootstrap_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_BUILD_ID, raising=False)
        monkeypatch.delenv(ENV_DEMO, raising=False)

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise DashboardConfigError("bad config")

        monkeypatch.setattr("credlens.dashboard.bootstrap.resolve_dashboard_config", _raise)
        with pytest.raises(BootstrapError, match="bad config"):
            load_validated_dashboard_data([])

    def test_unknown_build_becomes_bootstrap_error(self) -> None:
        with pytest.raises(BootstrapError):
            load_validated_dashboard_data(["--build-id", "BUILD_does_not_exist_anywhere"])

    def test_data_access_error_becomes_bootstrap_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from credlens.dashboard.data_access import DataAccessError

        monkeypatch.setattr(
            "credlens.dashboard.bootstrap.validate_dashboard_source", lambda _config: None
        )

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise DataAccessError("simulated data access failure")

        monkeypatch.setattr("credlens.dashboard.bootstrap.load_dashboard_data", _raise)
        with pytest.raises(BootstrapError, match="simulated data access failure"):
            load_validated_dashboard_data(["--demo"])


class TestDemoPackageSummary:
    def test_summarizes_a_real_demo_package(self, tmp_path: Path) -> None:
        import json
        from typing import Any

        manifest: dict[str, Any] = {
            "demo_package_version": "1.0.0",
            "source_build_id": "BUILD_x",
            "source_analysis_id": None,
            "warehouse_fingerprint": "fp",
            "package_version": "0.8.0",
            "generated_at": "2026-01-01T00:00:00Z",
            "tables": {},
            "insights_included": False,
            "total_size_bytes": 1234,
            "limitations": [],
        }
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        summary = demo_package_summary(tmp_path)
        assert "BUILD_x" in summary
        assert "1,234 bytes" in summary
