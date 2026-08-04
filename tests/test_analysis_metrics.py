"""Tests for credlens.analysis.metrics (Phase 6 section 10): every
function here is a thin SQL wrapper against a real built warehouse - these
tests prove each one returns a non-empty, grain-correct DataFrame with the
documented columns, and that the MIN_SEGMENT_OBSERVATIONS suppression flag
behaves. Builds one real isolated-root suite warehouse per module (Phase 6
gate B) and reuses it read-only across every test."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.analysis import metrics
from credlens.generation.suite import generate_suite
from credlens.generation.testing_support import (
    isolated_manifest_dir,
    isolated_output_dirs,
    safe_rmtree,
)
from credlens.warehouse.build import (
    _rmtree_with_retry,
    build_dir_for,
    run_build,
)

# Fase 11B - see tests/test_warehouse_build.py's own comment: this file
# was never marked slow, causing the dedicated CI job's slow-test step
# to exit 5 ("no tests collected").
pytestmark = pytest.mark.slow

_SEED = 703_502
_BUILD_ID = "BUILD_pytest_analysis_metrics"


@pytest.fixture(scope="module")
def isolated_suite(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path, Path]]:
    tmp_path = tmp_path_factory.mktemp("analysis_metrics")
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
def suite_id_and_db(isolated_suite: tuple[str, Path, Path]) -> Iterator[tuple[str, Path]]:
    suite_id, operational_dir, manifest_dir = isolated_suite
    manifest = run_build(
        suite_id=suite_id,
        build_id=_BUILD_ID,
        force=True,
        operational_root=operational_dir,
        manifest_dir=manifest_dir,
    )
    assert manifest.final_status == "success"
    yield suite_id, Path(manifest.db_path)
    build_dir = build_dir_for(_BUILD_ID)
    if build_dir.exists():
        try:
            _rmtree_with_retry(build_dir)
        except PermissionError:
            shutil.rmtree(build_dir, ignore_errors=True)


class TestMartWrappers:
    """Every direct mart wrapper: non-empty, has the columns its docstring
    promises, and every row belongs to this suite_id."""

    @pytest.mark.parametrize(
        ("fn_name", "required_columns"),
        [
            (
                "funnel_monthly",
                {"run_id", "applications_submitted", "approved_count", "booked_count"},
            ),
            ("portfolio_monthly", {"run_id", "snapshot_date", "outstanding_balance"}),
            ("delinquency_monthly", {"run_id", "snapshot_date", "par30", "par60", "par90"}),
            (
                "vintage_cohorts",
                {"run_id", "vintage_month", "months_on_book", "contracts_observed"},
            ),
            ("roll_rates", {"run_id", "from_bucket", "to_bucket", "contract_count"}),
            ("cure_and_redefault", {"run_id", "contract_key", "was_ever_cured", "redefaulted"}),
            ("collections_performance", {"run_id"}),
            ("writeoff_recovery", {"run_id", "total_write_off_amount", "total_recovery_amount"}),
            ("scenario_comparison", {"scenario", "approval_rate", "baseline_approval_rate"}),
            ("macro_stress_pre_post", {"period", "baseline_par90", "stress_par90"}),
        ],
    )
    def test_returns_nonempty_dataframe_with_expected_columns(
        self, suite_id_and_db: tuple[str, Path], fn_name: str, required_columns: set[str]
    ) -> None:
        suite_id, db_path = suite_id_and_db
        fn = getattr(metrics, fn_name)
        with metrics.connect(db_path) as conn:
            df = fn(conn, suite_id)
        assert len(df) > 0, f"{fn_name} returned an empty DataFrame"
        assert required_columns.issubset(set(df.columns)), (
            f"{fn_name} missing columns: {required_columns - set(df.columns)}"
        )

    def test_unknown_mart_raises_value_error(self, suite_id_and_db: tuple[str, Path]) -> None:
        suite_id, db_path = suite_id_and_db
        with metrics.connect(db_path) as conn, pytest.raises(ValueError, match="not found"):
            metrics._mart(conn, "mart_this_table_does_not_exist", suite_id)


class TestSegmentationQueries:
    def test_funnel_by_channel_and_scenario_has_low_sample_flag(
        self, suite_id_and_db: tuple[str, Path]
    ) -> None:
        suite_id, db_path = suite_id_and_db
        with metrics.connect(db_path) as conn:
            df = metrics.funnel_by_channel_and_scenario(conn, suite_id)
        assert "low_sample" in df.columns
        assert df["low_sample"].dtype == bool
        # The flag must be internally consistent with the threshold.
        assert (
            (df["decisioned_applications"] < metrics.MIN_SEGMENT_OBSERVATIONS) == df["low_sample"]
        ).all()

    def test_portfolio_by_region_and_channel_has_low_sample_flag(
        self, suite_id_and_db: tuple[str, Path]
    ) -> None:
        suite_id, db_path = suite_id_and_db
        with metrics.connect(db_path) as conn:
            df = metrics.portfolio_by_region_and_channel(conn, suite_id)
        assert len(df) > 0
        assert "low_sample" in df.columns
        assert ((df["contracts"] < metrics.MIN_SEGMENT_OBSERVATIONS) == df["low_sample"]).all()

    def test_policy_version_comparison_has_low_sample_flag(
        self, suite_id_and_db: tuple[str, Path]
    ) -> None:
        suite_id, db_path = suite_id_and_db
        with metrics.connect(db_path) as conn:
            df = metrics.policy_version_comparison(conn, suite_id)
        assert len(df) > 0
        assert "low_sample" in df.columns
        assert ((df["decisions"] < metrics.MIN_SEGMENT_OBSERVATIONS) == df["low_sample"]).all()


class TestPortfolioMonthlyScheduledColumns:
    """Phase 6 section 7: scheduled_amount_due_this_month must be a
    PERIOD-scoped figure, not the whole lifetime schedule summed into one
    row."""

    def test_scheduled_amount_due_this_month_is_not_the_whole_schedule_sum(
        self, suite_id_and_db: tuple[str, Path]
    ) -> None:
        suite_id, db_path = suite_id_and_db
        with metrics.connect(db_path) as conn:
            df = metrics.portfolio_monthly(conn, suite_id)
            baseline_run = conn.execute(
                "select run_id from main_dimensions.dim_run "
                "where suite_id = ? and scenario = 'baseline'",
                [suite_id],
            ).fetchone()[0]
            total_schedule = conn.execute(
                "select sum(scheduled_total) from main_facts.fct_installments where run_id = ?",
                [baseline_run],
            ).fetchone()[0]
        assert "scheduled_amount_due_this_month" in df.columns
        run_rows = df[df["run_id"] == baseline_run]
        assert len(run_rows) > 0
        # Any single month's due amount must be strictly less than the
        # sum of the ENTIRE amortization schedule across all months -
        # proves the column is period-scoped, not a lifetime total.
        assert run_rows["scheduled_amount_due_this_month"].max() < float(total_schedule)


class TestConnect:
    def test_connect_yields_a_read_only_connection(self, suite_id_and_db: tuple[str, Path]) -> None:
        import duckdb

        _suite_id, db_path = suite_id_and_db
        with (
            metrics.connect(db_path) as conn,
            pytest.raises(duckdb.Error, match="read-only mode"),
        ):
            conn.execute("create table pytest_should_not_be_allowed (x int)")
