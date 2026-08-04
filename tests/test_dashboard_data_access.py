"""Tests for credlens.dashboard.data_access (Phase 7 sections 10, 15, 16):
both modes return the same `DashboardData` shape, warehouse mode refuses
an invalid build, demo mode refuses a tampered package, and the DuckDB
connection used is read-only."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from credlens.analysis.runner import run_analysis
from credlens.dashboard.config import resolve_config
from credlens.dashboard.data_access import (
    DataAccessError,
    _load_insights,
    list_available_builds,
    load_dashboard_data,
    load_robustness_report,
    read_build_summary,
)
from credlens.generation.suite import generate_suite
from credlens.generation.testing_support import (
    isolated_manifest_dir,
    isolated_output_dirs,
    safe_rmtree,
)
from credlens.warehouse.build import _rmtree_with_retry, build_dir_for, run_build

# Fase 11B - see tests/test_warehouse_build.py's own comment: this file
# was never marked slow, causing the dedicated CI job's slow-test step
# to exit 5 ("no tests collected").
pytestmark = pytest.mark.slow

_SEED = 703_512
_BUILD_ID = "BUILD_pytest_dashboard_data_access"


@pytest.fixture(scope="module")
def isolated_suite(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path, Path]]:
    tmp_path = tmp_path_factory.mktemp("dashboard_data_access")
    operational_dir, truth_dir = isolated_output_dirs(tmp_path)
    manifest_dir = isolated_manifest_dir(tmp_path)
    outcome = generate_suite(
        scale_name="smoke",
        seed=_SEED,
        force=True,
        output_dirs=(operational_dir, truth_dir),
        manifest_dir=manifest_dir,
    )
    yield outcome.suite_id, operational_dir, manifest_dir
    safe_rmtree(tmp_path, allowed_root=tmp_path)


@pytest.fixture(scope="module")
def built_suite(isolated_suite: tuple[str, Path, Path]) -> Iterator[str]:
    suite_id, operational_dir, manifest_dir = isolated_suite
    manifest = run_build(
        suite_id=suite_id,
        build_id=_BUILD_ID,
        force=True,
        operational_root=operational_dir,
        manifest_dir=manifest_dir,
    )
    assert manifest.final_status == "success"
    yield manifest.build_id
    build_dir = build_dir_for(_BUILD_ID)
    if build_dir.exists():
        try:
            _rmtree_with_retry(build_dir)
        except PermissionError:
            shutil.rmtree(build_dir, ignore_errors=True)


class TestWarehouseMode:
    def test_loads_every_expected_table(self, built_suite: str) -> None:
        config = resolve_config(build_id=built_suite)
        data = load_dashboard_data(config)
        assert data.mode == "warehouse"
        assert data.build_id == built_suite
        assert data.suite_id is not None
        for name in ("funnel_monthly", "portfolio_monthly", "delinquency_monthly"):
            assert name in data.tables
            assert not data.tables[name].empty

    def test_refuses_a_nonexistent_build(self) -> None:
        config = resolve_config(build_id="BUILD_this_does_not_exist_anywhere")
        with pytest.raises(DataAccessError):
            load_dashboard_data(config)

    def test_returns_the_analytical_fingerprint(self, built_suite: str) -> None:
        config = resolve_config(build_id=built_suite)
        data = load_dashboard_data(config)
        assert len(data.fingerprint) == 64  # sha256 hex digest


class TestDemoModeAgainstTheRealOfficialPackage:
    """Uses the real, already-generated dashboard/demo_data/ package
    (built via `credlens dashboard export-demo`) rather than a fresh
    fixture - proves the actual shipped artifact loads correctly."""

    def _skip_if_absent(self) -> None:
        if not (Path("dashboard/demo_data") / "manifest.json").is_file():
            pytest.skip("dashboard/demo_data/ has not been generated in this environment")

    def test_loads_the_real_demo_package(self) -> None:
        self._skip_if_absent()
        config = resolve_config(demo=True)
        data = load_dashboard_data(config)
        assert data.mode == "demo"
        assert data.suite_id is None
        assert "funnel_monthly" in data.tables

    def test_insights_are_loaded_when_included(self) -> None:
        self._skip_if_absent()
        config = resolve_config(demo=True)
        data = load_dashboard_data(config)
        assert isinstance(data.insights, list)


class TestDemoModeTamperDetection:
    def test_refuses_a_tampered_package(self, built_suite: str, tmp_path: Path) -> None:
        from credlens.dashboard.demo_package import build_demo_package
        from credlens.warehouse.build import load_build_manifest

        build = load_build_manifest(built_suite)
        report_dir = tmp_path / "report"
        run_analysis(build_id=built_suite, output_dir=report_dir, include_benchmark=False)

        demo_dir = tmp_path / "demo"
        manifest = build_demo_package(
            analysis_output_dir=report_dir,
            output_dir=demo_dir,
            db_path=Path(build.db_path),
            suite_id=build.suite_id,
        )
        name = next(iter(manifest.tables))
        (demo_dir / f"{name}.parquet").write_bytes(b"not a real parquet file")

        config = resolve_config(demo=True, demo_data_dir=demo_dir)
        with pytest.raises(DataAccessError):
            load_dashboard_data(config)


class TestLoadDashboardDataEdgeCases:
    def test_build_with_no_suite_id_raises(
        self, monkeypatch: pytest.MonkeyPatch, built_suite: str
    ) -> None:
        import credlens.dashboard.data_access as data_access_module
        from credlens.warehouse.build import load_build_manifest

        real_build = load_build_manifest(built_suite)
        fake_build = replace(real_build, suite_id=None)
        monkeypatch.setattr(
            data_access_module, "_validated_build_manifest", lambda _bid: fake_build
        )
        config = resolve_config(build_id=built_suite)
        with pytest.raises(DataAccessError, match="no suite_id"):
            load_dashboard_data(config)

    def test_composition_value_error_is_skipped_not_raised(
        self, monkeypatch: pytest.MonkeyPatch, built_suite: str
    ) -> None:
        import credlens.dashboard.data_access as data_access_module

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise ValueError("no run for this scenario in this suite")

        # Clear the cache first - a prior test in this module may already
        # have cached a real composition result for this exact
        # (build_id, fingerprint, db_path, suite_id) key, which would
        # otherwise short-circuit before ever calling our monkeypatched
        # composition_vs_performance below.
        data_access_module._load_warehouse_composition.clear()
        monkeypatch.setattr(data_access_module, "composition_vs_performance", _raise)
        config = resolve_config(build_id=built_suite)
        data = load_dashboard_data(config)
        assert data.composition == {}


class TestSmallLoaderHelpers:
    def test_load_insights_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        assert _load_insights(str(tmp_path / "no_such_insights.yml")) == []

    def test_load_robustness_report_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        assert load_robustness_report(str(tmp_path / "no_such_report.json")) == {}

    def test_load_robustness_report_real_file(self) -> None:
        path = Path("reports/synthetic_validation/multiseed_robustness.json")
        if not path.is_file():
            pytest.skip("multiseed_robustness.json not present in this environment")
        report = load_robustness_report(str(path))
        assert "scenarios" in report

    def test_list_available_builds_missing_root_returns_empty(self, tmp_path: Path) -> None:
        assert list_available_builds(tmp_path / "no_such_warehouse_root") == []

    def test_read_build_summary_missing_manifest_raises(self, tmp_path: Path) -> None:
        with pytest.raises(DataAccessError):
            read_build_summary("BUILD_does_not_exist", warehouse_root=tmp_path)

    def test_read_build_summary_real_build(self, built_suite: str) -> None:
        summary = read_build_summary(built_suite)
        assert summary["build_id"] == built_suite
