"""Metamorphic tests for the Phase 6 analysis/warehouse pipeline (section
21): properties that must hold no matter what the exact data is, checked
by comparing two runs of the pipeline under a controlled data
transformation rather than asserting a specific number.

Two of the six required properties are proven elsewhere and referenced,
not duplicated, here:
  - "perturbing sources after a build must block analysis" -
    tests/test_analysis_validation.py::TestValidateBuildForAnalysis::
    test_tampered_raw_source_is_detected_and_refused
  - "running the same analysis twice must produce the same content
    fingerprint" - tests/test_analysis_runner.py::TestRunAnalysisIsReproducible

This file covers the remaining four:
  - physically reordering rows must not change a table's canonical hash
  - duplicating an event table must not change a stock metric
  - adding future not-yet-due installments must not change the current
    period's scheduled-due amount
  - appending a future (post-observed) snapshot row must not change
    already-reported historical results
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from credlens.generation.config import DEFAULT_CONFIG_PATH, load_generation_config, with_output_dirs
from credlens.generation.manifest import canonical_run_hash, canonical_table_hash
from credlens.generation.orchestrator import generate_scenario
from credlens.generation.testing_support import isolated_output_dirs, safe_rmtree
from credlens.warehouse.build import BuildManifest, _rmtree_with_retry, build_dir_for, run_build

_SEED = 703_506
_ORIGINAL_BUILD_ID = "BUILD_pytest_metamorphic_original"
_MUTATED_BUILD_ID = "BUILD_pytest_metamorphic_mutated"


class TestCanonicalTableHashIsRowOrderIndependent:
    """Property 4: physically reordering rows must not change the
    content hash a build/reconciliation/integrity check relies on. Pure
    function test - no warehouse needed."""

    def test_shuffled_rows_hash_identically_to_the_original_order(self) -> None:
        df = pd.DataFrame(
            {
                "id": [f"ROW_{i:04d}" for i in range(200)],
                "amount": [i * 1.11 for i in range(200)],
                "flag": [i % 3 == 0 for i in range(200)],
                "note": [None if i % 7 == 0 else f"note-{i}" for i in range(200)],
            }
        )
        shuffled = df.sample(frac=1.0, random_state=42).reset_index(drop=True)
        assert not df.equals(shuffled)  # sanity: the shuffle actually did something
        assert canonical_table_hash(df) == canonical_table_hash(shuffled)

    def test_reordered_columns_hash_identically_too(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        reordered = df[["b", "a"]]
        assert canonical_table_hash(df) == canonical_table_hash(reordered)

    def test_a_genuinely_different_value_does_change_the_hash(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        mutated = pd.DataFrame({"a": [1, 2, 4]})
        assert canonical_table_hash(df) != canonical_table_hash(mutated)


def _remanifest_after_mutation(run_dir: Path) -> None:
    """Recomputes table_hashes/row_counts/global_content_hash from
    whatever is currently on disk under run_dir/operational/ and rewrites
    run_dir/manifest.json to match - simulating "the generator had
    legitimately produced this exact content", never a tampering
    scenario (Phase 6 gate C's own negative test covers tampering
    separately, by mutating WITHOUT re-manifesting)."""
    manifest_path = run_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    operational_dir = run_dir / "operational"

    table_hashes: dict[str, str] = {}
    table_row_counts: dict[str, int] = {}
    for parquet_path in sorted(operational_dir.glob("*.parquet")):
        name = parquet_path.stem
        df = pd.read_parquet(parquet_path)
        table_row_counts[name] = len(df)
        if name != "generation_runs":
            table_hashes[name] = canonical_table_hash(df)

    global_hash = canonical_run_hash(
        table_hashes,
        str(payload["config_hash"]),
        int(payload["seed"]),
        str(payload["scenario"]),
        str(payload["scale"]),
    )
    payload["tables"] = {
        name: {
            "row_count": table_row_counts.get(name, 0),
            "canonical_hash": table_hashes.get(name, ""),
        }
        for name in sorted(table_hashes)
    }
    payload["global_content_hash"] = global_hash
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")


def _apply_combined_mutations(run_dir: Path) -> None:
    operational_dir = run_dir / "operational"

    # (1) Duplicate every write_off_events row (with fresh, still-unique
    # ids - a real duplicate EVENT, not a primary-key collision) - an
    # EVENT table growing must never move a STOCK metric
    # (outstanding_balance comes from account_monthly_snapshots, not from
    # write_off_events).
    wo_path = operational_dir / "write_off_events.parquet"
    wo = pd.read_parquet(wo_path)
    if len(wo) > 0:
        duplicated = wo.copy()
        duplicated["write_off_id"] = [f"{wid}_DUP" for wid in duplicated["write_off_id"]]
        pd.concat([wo, duplicated], ignore_index=True).to_parquet(wo_path, index=False)

    # (2) Append one far-future installment (due 5 years past the run's
    # own last due_date) - must not change scheduled_amount_due_this_month
    # for any ALREADY-OBSERVED period (there is no snapshot that far out,
    # so this new due_month can never join to an existing mart row).
    inst_path = operational_dir / "installments.parquet"
    inst = pd.read_parquet(inst_path)
    future_row = inst.iloc[[0]].copy()
    future_due_date = pd.to_datetime(inst["due_date"]).max() + pd.DateOffset(years=5)
    future_row["due_date"] = future_due_date.date().isoformat()
    future_row["installment_id"] = "INST_future_metamorphic_0000000001"
    pd.concat([inst, future_row], ignore_index=True).to_parquet(inst_path, index=False)

    # (3) Append one future (post-observed) account_monthly_snapshots row,
    # cloned from a contract that is still 'active' at the run's own last
    # snapshot_date (never a terminal-status contract, which would
    # spuriously violate assert_no_active_contract_after_terminal_status)
    # - must not change any HISTORICAL snapshot_date's own metrics (no
    # window function looks forward in mart_delinquency_monthly/
    # mart_portfolio_monthly - each snapshot_date is an independent group).
    snap_path = operational_dir / "account_monthly_snapshots.parquet"
    snap = pd.read_parquet(snap_path)
    last_date = snap["snapshot_date"].max()
    still_active = snap[(snap["snapshot_date"] == last_date) & (snap["status"] == "active")]
    future_snap_row = still_active.iloc[[0]].copy()
    future_snapshot_date = pd.to_datetime(last_date) + pd.DateOffset(months=1)
    future_snap_row["snapshot_date"] = future_snapshot_date.date().isoformat()
    pd.concat([snap, future_snap_row], ignore_index=True).to_parquet(snap_path, index=False)

    _remanifest_after_mutation(run_dir)


@pytest.fixture(scope="module")
def original_and_mutated_builds(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[str, str]]:
    tmp_path = tmp_path_factory.mktemp("metamorphic")
    operational_dir, truth_dir = isolated_output_dirs(tmp_path)
    config = with_output_dirs(
        load_generation_config(DEFAULT_CONFIG_PATH),
        operational_dir=operational_dir,
        truth_dir=truth_dir,
    )
    outcome = generate_scenario(
        scenario="baseline", scale_name="smoke", seed=_SEED, force=True, config_override=config
    )
    run_id = outcome.generation_run_id

    mutated_root = tmp_path / "synthetic_mutated"
    mutated_root.mkdir(parents=True)
    mutated_run_dir = mutated_root / run_id
    shutil.copytree(operational_dir / run_id, mutated_run_dir)
    _apply_combined_mutations(mutated_run_dir)

    original_manifest = run_build(
        run_id=run_id, build_id=_ORIGINAL_BUILD_ID, force=True, operational_root=operational_dir
    )
    mutated_manifest = run_build(
        run_id=run_id, build_id=_MUTATED_BUILD_ID, force=True, operational_root=mutated_root
    )
    assert original_manifest.final_status == "success"
    assert mutated_manifest.final_status == "success"

    yield original_manifest.build_id, mutated_manifest.build_id

    for build_id in (_ORIGINAL_BUILD_ID, _MUTATED_BUILD_ID):
        build_dir = build_dir_for(build_id)
        if build_dir.exists():
            try:
                _rmtree_with_retry(build_dir)
            except PermissionError:
                shutil.rmtree(build_dir, ignore_errors=True)
    safe_rmtree(tmp_path, allowed_root=tmp_path)


def _restrict_to_original_dates(
    original_df: pd.DataFrame, mutated_df: pd.DataFrame
) -> pd.DataFrame:
    """The combined mutation fixture adds a genuinely new snapshot_date
    (mutation 3) on top of the other two mutations, so every
    snapshot-grain mart legitimately gains one extra row in the mutated
    build - restrict to the original's own observed dates (in Python, not
    fragile SQL) before asserting every HISTORICAL row is unchanged."""
    original_dates = set(original_df["snapshot_date"])
    return mutated_df[mutated_df["snapshot_date"].isin(original_dates)].reset_index(drop=True)


def _connect(build_id: str) -> tuple[Any, BuildManifest]:
    import duckdb

    from credlens.warehouse.build import load_build_manifest

    manifest = load_build_manifest(build_id)
    return duckdb.connect(manifest.db_path, read_only=True), manifest


class TestDuplicatingAnEventTableDoesNotChangeAStockMetric:
    def test_outstanding_balance_is_identical_across_every_observed_snapshot_date(
        self, original_and_mutated_builds: tuple[str, str]
    ) -> None:
        original_id, mutated_id = original_and_mutated_builds
        conn_o, _m_o = _connect(original_id)
        conn_m, _m_m = _connect(mutated_id)
        try:
            original_df = conn_o.execute(
                "select snapshot_date, outstanding_balance from main_marts.mart_portfolio_monthly "
                "order by snapshot_date"
            ).fetchdf()
            mutated_df_all = conn_m.execute(
                "select snapshot_date, outstanding_balance from main_marts.mart_portfolio_monthly "
                "order by snapshot_date"
            ).fetchdf()
        finally:
            conn_o.close()
            conn_m.close()

        assert len(original_df) > 0
        mutated_df = _restrict_to_original_dates(original_df, mutated_df_all)
        assert len(mutated_df) == len(original_df)
        pd.testing.assert_frame_equal(original_df, mutated_df)

    def test_write_off_recovery_mart_does_show_the_duplication(
        self, original_and_mutated_builds: tuple[str, str]
    ) -> None:
        """Sanity check that the mutation was real: total_write_off_amount
        (which DOES depend on write_off_events) must have changed - proving
        the identical outstanding_balance above is a genuine structural
        property, not an artifact of the mutation silently not landing."""
        original_id, mutated_id = original_and_mutated_builds
        conn_o, _ = _connect(original_id)
        conn_m, _ = _connect(mutated_id)
        try:
            original_total = conn_o.execute(
                "select sum(total_write_off_amount) from main_marts.mart_writeoff_recovery"
            ).fetchone()[0]
            mutated_total = conn_m.execute(
                "select sum(total_write_off_amount) from main_marts.mart_writeoff_recovery"
            ).fetchone()[0]
        finally:
            conn_o.close()
            conn_m.close()
        if original_total:  # only meaningful if this seed produced any write-offs at all
            assert float(mutated_total) == pytest.approx(float(original_total) * 2)


class TestFutureInstallmentsDoNotChangeCurrentPeriodScheduled:
    def test_scheduled_amount_due_this_month_is_identical_for_every_observed_snapshot(
        self, original_and_mutated_builds: tuple[str, str]
    ) -> None:
        original_id, mutated_id = original_and_mutated_builds
        conn_o, _ = _connect(original_id)
        conn_m, _ = _connect(mutated_id)
        try:
            original_df = conn_o.execute(
                "select snapshot_date, scheduled_amount_due_this_month "
                "from main_marts.mart_portfolio_monthly order by snapshot_date"
            ).fetchdf()
            mutated_df_all = conn_m.execute(
                "select snapshot_date, scheduled_amount_due_this_month "
                "from main_marts.mart_portfolio_monthly order by snapshot_date"
            ).fetchdf()
        finally:
            conn_o.close()
            conn_m.close()

        assert len(original_df) > 0
        mutated_df = _restrict_to_original_dates(original_df, mutated_df_all)
        assert len(mutated_df) == len(original_df)
        pd.testing.assert_frame_equal(original_df, mutated_df)


class TestFutureSnapshotDoesNotChangeHistoricalResults:
    def test_par90_is_identical_for_every_previously_observed_snapshot_date(
        self, original_and_mutated_builds: tuple[str, str]
    ) -> None:
        original_id, mutated_id = original_and_mutated_builds
        conn_o, _ = _connect(original_id)
        conn_m, _ = _connect(mutated_id)
        query = (
            "select snapshot_date, par30, par60, par90 "
            "from main_marts.mart_delinquency_monthly order by snapshot_date"
        )
        try:
            original_df = conn_o.execute(query).fetchdf()
            mutated_df_all = conn_m.execute(query).fetchdf()
        finally:
            conn_o.close()
            conn_m.close()

        assert len(original_df) > 0
        mutated_df = _restrict_to_original_dates(original_df, mutated_df_all)
        assert len(mutated_df) == len(original_df)
        pd.testing.assert_frame_equal(original_df, mutated_df)

    def test_mutated_build_does_have_one_extra_future_snapshot_date(
        self, original_and_mutated_builds: tuple[str, str]
    ) -> None:
        """Sanity check the mutation landed: the mutated build must show
        MORE distinct snapshot_dates than the original."""
        original_id, mutated_id = original_and_mutated_builds
        conn_o, _ = _connect(original_id)
        conn_m, _ = _connect(mutated_id)
        try:
            n_original = conn_o.execute(
                "select count(distinct snapshot_date) from main_marts.mart_delinquency_monthly"
            ).fetchone()[0]
            n_mutated = conn_m.execute(
                "select count(distinct snapshot_date) from main_marts.mart_delinquency_monthly"
            ).fetchone()[0]
        finally:
            conn_o.close()
            conn_m.close()
        assert n_mutated == n_original + 1
