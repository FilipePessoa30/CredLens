"""Tests for credlens.dashboard.validation (Phase 7 sections 10, 16, 19,
20): the dashboard must refuse a build with no suite_id and a demo
package that fails its own integrity check, both wrapped into a single
`DashboardValidationError` type regardless of the underlying cause."""

from __future__ import annotations

from pathlib import Path

import pytest

from credlens.dashboard.config import resolve_config
from credlens.dashboard.validation import DashboardValidationError, validate_dashboard_source


class TestValidateDashboardSourceWarehouseMode:
    def test_build_with_no_suite_id_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from credlens.warehouse.build import BuildManifest

        fake_build = BuildManifest(
            build_id="BUILD_single_run",
            db_path="data/warehouse/BUILD_single_run/warehouse.duckdb",
            run_id="RUN_baseline_smoke_1_abc",
            suite_id=None,
            included_run_ids=["RUN_baseline_smoke_1_abc"],
            code_version="0.8.0",
            dbt_version="1.12.0",
            duckdb_version="1.5.5",
            sources=[],
            raw_row_counts={},
            model_row_counts={},
            test_results={"passed": 1, "failed": 0, "errored": 0, "skipped": 0, "failures": []},
            step_durations={},
            analytical_fingerprint="fp",
            final_status="success",
            built_at="2026-01-01T00:00:00Z",
        )
        monkeypatch.setattr(
            "credlens.dashboard.validation.validate_build_for_analysis", lambda _bid: fake_build
        )
        config = resolve_config(build_id="BUILD_single_run")
        with pytest.raises(DashboardValidationError, match="no suite_id"):
            validate_dashboard_source(config)

    def test_unknown_build_is_refused(self) -> None:
        config = resolve_config(build_id="BUILD_does_not_exist_anywhere")
        with pytest.raises(DashboardValidationError):
            validate_dashboard_source(config)


class TestValidateDashboardSourceDemoMode:
    def test_missing_demo_package_is_refused(self, tmp_path: Path) -> None:
        config = resolve_config(demo=True, demo_data_dir=tmp_path / "no_such_demo")
        with pytest.raises(DashboardValidationError):
            validate_dashboard_source(config)
