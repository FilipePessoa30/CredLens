"""Tests for credlens.dashboard.config (Phase 7 section 19): explicit
mode selection, no silent default, no path-traversal build ids."""

from __future__ import annotations

from pathlib import Path

import pytest

from credlens.dashboard.config import DashboardConfigError, resolve_config


class TestResolveConfig:
    def test_requires_exactly_one_mode(self) -> None:
        with pytest.raises(DashboardConfigError, match="Neither"):
            resolve_config()

    def test_rejects_both_modes_at_once(self) -> None:
        with pytest.raises(DashboardConfigError, match="Both"):
            resolve_config(build_id="BUILD_x", demo=True)

    def test_warehouse_mode(self) -> None:
        config = resolve_config(build_id="BUILD_kpi_test")
        assert config.mode == "warehouse"
        assert config.build_id == "BUILD_kpi_test"

    def test_demo_mode(self) -> None:
        config = resolve_config(demo=True)
        assert config.mode == "demo"
        assert config.build_id is None

    @pytest.mark.parametrize("bad_id", ["../etc/passwd", "a/b", "a\\b", "a..b\x00"])
    def test_rejects_path_traversal_build_ids(self, bad_id: str) -> None:
        with pytest.raises(DashboardConfigError):
            resolve_config(build_id=bad_id)

    def test_rejects_invalid_port(self) -> None:
        with pytest.raises(DashboardConfigError):
            resolve_config(demo=True, port=0)
        with pytest.raises(DashboardConfigError):
            resolve_config(demo=True, port=70000)

    def test_default_demo_data_dir(self) -> None:
        config = resolve_config(demo=True)
        assert config.demo_data_dir == Path("dashboard/demo_data")

    def test_custom_demo_data_dir(self, tmp_path: Path) -> None:
        config = resolve_config(demo=True, demo_data_dir=tmp_path)
        assert config.demo_data_dir == tmp_path

    def test_to_dict_round_trips_every_field(self) -> None:
        config = resolve_config(build_id="BUILD_x", port=9000, open_browser=False)
        d = config.to_dict()
        assert d == {
            "mode": "warehouse",
            "build_id": "BUILD_x",
            "demo_data_dir": str(config.demo_data_dir),
            "port": 9000,
            "open_browser": False,
        }
