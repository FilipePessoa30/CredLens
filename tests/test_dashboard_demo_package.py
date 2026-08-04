"""Tests for credlens.dashboard.demo_package (Phase 7 section 18): the
demo package must never carry a customer/contract-identifying column,
must detect tampering, must stay under its size budget, and its KPIs
must reconcile with the warehouse it was built from."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

import credlens.dashboard.demo_package as demo_package_module
from credlens.analysis.runner import run_analysis
from credlens.dashboard.demo_package import (
    DEMO_PACKAGE_SIZE_BUDGET_BYTES,
    DemoPackageError,
    _aggregate_cure_and_redefault,
    build_demo_package,
    load_demo_manifest,
    validate_demo_package,
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

_SEED = 703_511
_BUILD_ID = "BUILD_pytest_dashboard_demo_package"


@pytest.fixture(scope="module")
def isolated_suite(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path, Path]]:
    tmp_path = tmp_path_factory.mktemp("dashboard_demo")
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
def analysis_output(
    isolated_suite: tuple[str, Path, Path], tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[Path, str, str]]:
    suite_id, operational_dir, manifest_dir = isolated_suite
    manifest = run_build(
        suite_id=suite_id,
        build_id=_BUILD_ID,
        force=True,
        operational_root=operational_dir,
        manifest_dir=manifest_dir,
    )
    assert manifest.final_status == "success"
    output_dir = tmp_path_factory.mktemp("dashboard_demo_report")
    run_analysis(build_id=manifest.build_id, output_dir=output_dir, include_benchmark=False)
    yield output_dir, manifest.db_path, str(suite_id)
    build_dir = build_dir_for(_BUILD_ID)
    if build_dir.exists():
        try:
            _rmtree_with_retry(build_dir)
        except PermissionError:
            shutil.rmtree(build_dir, ignore_errors=True)


class TestBuildDemoPackage:
    def test_builds_a_manifest_with_no_forbidden_columns(
        self, analysis_output: tuple[Path, str, str], tmp_path: Path
    ) -> None:
        output_dir, db_path, suite_id = analysis_output
        out = tmp_path / "demo"
        manifest = build_demo_package(
            analysis_output_dir=output_dir, output_dir=out, db_path=Path(db_path), suite_id=suite_id
        )
        assert manifest.total_size_bytes <= DEMO_PACKAGE_SIZE_BUDGET_BYTES
        for name in manifest.tables:
            df = pd.read_parquet(out / f"{name}.parquet")
            forbidden = {"contract_key", "contract_id", "customer_key", "customer_id"} & set(
                df.columns
            )
            assert not forbidden, f"{name} carries forbidden column(s) {forbidden}"

    def test_cure_and_redefault_is_aggregated_not_per_contract(
        self, analysis_output: tuple[Path, str, str], tmp_path: Path
    ) -> None:
        output_dir, db_path, suite_id = analysis_output
        out = tmp_path / "demo2"
        manifest = build_demo_package(
            analysis_output_dir=output_dir, output_dir=out, db_path=Path(db_path), suite_id=suite_id
        )
        assert "cure_redefault_summary" in manifest.tables
        summary = pd.read_parquet(out / "cure_redefault_summary.parquet")
        assert "contract_key" not in summary.columns
        assert "n_ever_cured" in summary.columns

    def test_raises_when_no_analysis_manifest_exists(self, tmp_path: Path) -> None:
        with pytest.raises(DemoPackageError):
            build_demo_package(analysis_output_dir=tmp_path / "nope", output_dir=tmp_path / "out")

    def test_includes_insights_when_present(
        self, analysis_output: tuple[Path, str, str], tmp_path: Path
    ) -> None:
        from credlens.analysis.insights import generate_insights, write_insights_registry

        output_dir, db_path, suite_id = analysis_output
        insights = generate_insights(output_dir)
        write_insights_registry(insights, output_dir / "insights.yml")

        out = tmp_path / "demo3"
        manifest = build_demo_package(
            analysis_output_dir=output_dir, output_dir=out, db_path=Path(db_path), suite_id=suite_id
        )
        assert manifest.insights_included is True
        assert (out / "insights.yml").is_file()


class TestValidateDemoPackage:
    def test_valid_package_passes(
        self, analysis_output: tuple[Path, str, str], tmp_path: Path
    ) -> None:
        output_dir, db_path, suite_id = analysis_output
        out = tmp_path / "demo_valid"
        build_demo_package(
            analysis_output_dir=output_dir, output_dir=out, db_path=Path(db_path), suite_id=suite_id
        )
        manifest = validate_demo_package(out)
        assert len(manifest.tables) > 0

    def test_tampered_table_is_detected(
        self, analysis_output: tuple[Path, str, str], tmp_path: Path
    ) -> None:
        output_dir, db_path, suite_id = analysis_output
        out = tmp_path / "demo_tamper"
        manifest = build_demo_package(
            analysis_output_dir=output_dir, output_dir=out, db_path=Path(db_path), suite_id=suite_id
        )
        name = next(iter(manifest.tables))
        df = pd.read_parquet(out / f"{name}.parquet")
        df.iloc[0:1].to_parquet(out / f"{name}.parquet")  # truncate to 1 row - changes the hash

        with pytest.raises(DemoPackageError, match="integrity"):
            validate_demo_package(out)

    def test_missing_table_is_detected(
        self, analysis_output: tuple[Path, str, str], tmp_path: Path
    ) -> None:
        output_dir, db_path, suite_id = analysis_output
        out = tmp_path / "demo_missing"
        manifest = build_demo_package(
            analysis_output_dir=output_dir, output_dir=out, db_path=Path(db_path), suite_id=suite_id
        )
        name = next(iter(manifest.tables))
        (out / f"{name}.parquet").unlink()

        with pytest.raises(DemoPackageError, match="missing"):
            validate_demo_package(out)

    def test_missing_manifest_is_detected(self, tmp_path: Path) -> None:
        with pytest.raises(DemoPackageError):
            validate_demo_package(tmp_path)

    def test_load_demo_manifest_round_trips(
        self, analysis_output: tuple[Path, str, str], tmp_path: Path
    ) -> None:
        output_dir, db_path, suite_id = analysis_output
        out = tmp_path / "demo_roundtrip"
        original = build_demo_package(
            analysis_output_dir=output_dir, output_dir=out, db_path=Path(db_path), suite_id=suite_id
        )
        loaded = load_demo_manifest(out)
        assert loaded.source_build_id == original.source_build_id
        assert loaded.tables.keys() == original.tables.keys()


class TestAggregateCureAndRedefaultEmptyInput:
    def test_empty_dataframe_returns_empty_with_expected_columns(self) -> None:
        result = _aggregate_cure_and_redefault(pd.DataFrame())
        assert list(result.columns) == [
            "run_id",
            "suite_id",
            "scenario",
            "n_contracts",
            "n_ever_cured",
            "n_redefaulted",
            "cure_incidence",
            "redefault_rate",
        ]
        assert result.empty


class TestBuildDemoPackageEdgeCases:
    def test_a_forbidden_column_in_a_passthrough_csv_is_rejected(
        self, analysis_output: tuple[Path, str, str], tmp_path: Path
    ) -> None:
        output_dir, db_path, suite_id = analysis_output
        tampered_dir = tmp_path / "tampered_report"
        import shutil as shutil_module

        shutil_module.copytree(output_dir, tampered_dir)
        funnel_csv = tampered_dir / "tables" / "funnel_monthly.csv"
        df = pd.read_csv(funnel_csv)
        df["contract_id"] = "should_not_be_here"
        df.to_csv(funnel_csv, index=False)

        with pytest.raises(DemoPackageError, match="contract/customer-identifying"):
            build_demo_package(
                analysis_output_dir=tampered_dir,
                output_dir=tmp_path / "demo_forbidden",
                db_path=Path(db_path),
                suite_id=suite_id,
            )

    def test_a_missing_passthrough_csv_is_skipped_not_an_error(
        self, analysis_output: tuple[Path, str, str], tmp_path: Path
    ) -> None:
        output_dir, db_path, suite_id = analysis_output
        thinned_dir = tmp_path / "thinned_report"
        import shutil as shutil_module

        shutil_module.copytree(output_dir, thinned_dir)
        (thinned_dir / "tables" / "roll_rates.csv").unlink()

        manifest = build_demo_package(
            analysis_output_dir=thinned_dir,
            output_dir=tmp_path / "demo_thinned",
            db_path=Path(db_path),
            suite_id=suite_id,
        )
        assert "roll_rates" not in manifest.tables


class TestSizeBudgetEnforcement:
    def test_exceeding_the_budget_raises(
        self,
        analysis_output: tuple[Path, str, str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        output_dir, db_path, suite_id = analysis_output
        monkeypatch.setattr(demo_package_module, "DEMO_PACKAGE_SIZE_BUDGET_BYTES", 1)
        with pytest.raises(DemoPackageError, match="exceeds"):
            build_demo_package(
                analysis_output_dir=output_dir,
                output_dir=tmp_path / "demo_over_budget",
                db_path=Path(db_path),
                suite_id=suite_id,
            )


class TestValidateDetectsForbiddenColumnEvenIfHashMatches:
    def test_forbidden_column_written_directly_is_rejected(self, tmp_path: Path) -> None:
        import hashlib
        import json
        from typing import Any

        table_path = tmp_path / "sneaky_table.parquet"
        pd.DataFrame({"contract_id": ["x"], "value": [1]}).to_parquet(table_path)
        digest = hashlib.sha256(table_path.read_bytes()).hexdigest()
        manifest: dict[str, Any] = {
            "demo_package_version": "1.0.0",
            "source_build_id": "BUILD_x",
            "source_analysis_id": None,
            "warehouse_fingerprint": "fp",
            "package_version": "0.8.0",
            "generated_at": "2026-01-01T00:00:00Z",
            "tables": {
                "sneaky_table": {
                    "row_count": 1,
                    "sha256": digest,
                    "provenance": "synthetic_scenario",
                    "size_bytes": table_path.stat().st_size,
                }
            },
            "insights_included": False,
            "total_size_bytes": table_path.stat().st_size,
            "limitations": [],
        }
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        with pytest.raises(DemoPackageError, match="forbidden"):
            validate_demo_package(tmp_path)


class TestDemoWarehouseReconciliation:
    """Phase 7 section 18.4: demo and warehouse must agree on the same
    aggregate KPIs - proven here by re-deriving one KPI (total
    outstanding balance, final snapshot, baseline) both ways."""

    def test_outstanding_balance_matches_between_demo_and_warehouse(
        self, analysis_output: tuple[Path, str, str], tmp_path: Path
    ) -> None:
        output_dir, db_path, suite_id = analysis_output
        out = tmp_path / "demo_reconcile"
        build_demo_package(
            analysis_output_dir=output_dir, output_dir=out, db_path=Path(db_path), suite_id=suite_id
        )

        warehouse_df = pd.read_csv(output_dir / "tables" / "portfolio_monthly.csv")
        demo_df = pd.read_parquet(out / "portfolio_monthly.parquet")

        def _final_baseline_balance(df: pd.DataFrame) -> float:
            base = df[df["scenario"] == "baseline"].sort_values("snapshot_date")
            return float(base["outstanding_balance"].iloc[-1])

        assert _final_baseline_balance(warehouse_df) == _final_baseline_balance(demo_df)
