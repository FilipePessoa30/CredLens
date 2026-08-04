"""Tests for credlens.warehouse.integrity (Phase 6 gate C): the raw layer
is a DuckDB view over external parquet, so a build's own manifest can
only be trusted if it is re-verified against what is CURRENTLY on disk
every time something reads through it. Uses an isolated-root run (Phase 6
gate B) so the mandatory negative test - mutating a parquet file after
the build - never touches real shared data."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

from credlens.generation.config import DEFAULT_CONFIG_PATH, load_generation_config, with_output_dirs
from credlens.generation.orchestrator import generate_scenario
from credlens.generation.testing_support import isolated_output_dirs, safe_rmtree
from credlens.warehouse.build import (
    _rmtree_with_retry,
    build_dir_for,
    load_build_manifest,
    run_build,
)
from credlens.warehouse.integrity import IntegrityViolation, RawIntegrityError, verify_build_sources
from credlens.warehouse.queries import run_named_query
from credlens.warehouse.reconciliation import run_reconciliation

# Fase 11B - see tests/test_warehouse_build.py's own comment: this file
# was never marked slow, causing the dedicated CI job's slow-test step
# to exit 5 ("no tests collected").
pytestmark = pytest.mark.slow

_SEED = 615_304
_BUILD_ID = "BUILD_pytest_integrity"


@pytest.fixture(scope="module")
def isolated_run(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path, Path]]:
    """A real generation run rooted under an isolated tmp_path (Phase 6
    gate B) - never the shared data/synthetic/ tree - so mutating its
    parquet after the build is a mutation of throwaway test data, not
    real demonstration data. Yields (run_id, operational_root, tables_dir)
    - operational_root is the run-id-containing directory `run_build`
    resolves against; tables_dir is that specific run's own
    `.../<run_id>/operational/` directory, where the actual parquet
    files and this run's own manifest.json live."""
    tmp_path = tmp_path_factory.mktemp("gate_c_integrity")
    operational_root, truth_dir = isolated_output_dirs(tmp_path)
    config = with_output_dirs(
        load_generation_config(DEFAULT_CONFIG_PATH),
        operational_dir=operational_root,
        truth_dir=truth_dir,
    )
    outcome = generate_scenario(
        scenario="baseline", scale_name="smoke", seed=_SEED, force=True, config_override=config
    )
    tables_dir = outcome.operational_dir / "operational"
    yield outcome.generation_run_id, operational_root, tables_dir
    safe_rmtree(tmp_path, allowed_root=tmp_path)


@pytest.fixture(scope="module")
def a_built_warehouse(isolated_run: tuple[str, Path, Path]) -> Iterator[str]:
    run_id, operational_root, _tables_dir = isolated_run
    manifest = run_build(
        run_id=run_id,
        build_id=_BUILD_ID,
        force=True,
        operational_root=operational_root,
    )
    assert manifest.final_status == "success"
    yield manifest.build_id
    build_dir = build_dir_for(_BUILD_ID)
    if build_dir.exists():
        try:
            _rmtree_with_retry(build_dir)
        except PermissionError:
            shutil.rmtree(build_dir, ignore_errors=True)


class TestVerifyBuildSourcesOnUnmutatedData:
    def test_passes_cleanly_right_after_a_build(self, a_built_warehouse: str) -> None:
        manifest = load_build_manifest(a_built_warehouse)
        verify_build_sources(manifest.sources)  # must not raise

    def test_reconciliation_runs_normally_on_unmutated_data(self, a_built_warehouse: str) -> None:
        manifest = load_build_manifest(a_built_warehouse)
        results = run_reconciliation(Path(manifest.db_path), manifest.sources)
        assert all(r.passed for r in results)

    def test_named_query_runs_normally_on_unmutated_data(self, a_built_warehouse: str) -> None:
        manifest = load_build_manifest(a_built_warehouse)
        columns, _rows = run_named_query(
            Path(manifest.db_path), "portfolio_monthly", manifest.sources
        )
        assert columns


class TestPostBuildParquetMutationIsDetected:
    """The mandatory negative test (Phase 6 gate C section 6.3): mutate a
    parquet file AFTER the build exists, prove verification detects it,
    and prove both reconcile and query refuse to run against it."""

    def test_mutating_a_row_value_is_detected_and_blocks_everything(
        self, isolated_run: tuple[str, Path, Path], a_built_warehouse: str
    ) -> None:
        _run_id, _operational_root, operational_dir = isolated_run
        manifest = load_build_manifest(a_built_warehouse)

        # customers.parquet always has rows (n_customers > 0 at every
        # scale) - unlike write_off_events, this table never needs a
        # skip-if-empty escape hatch.
        table_path = operational_dir / "customers.parquet"
        original_bytes = table_path.read_bytes()
        try:
            df = pd.read_parquet(table_path)
            assert len(df) > 0
            mutated_column = "customer_id"
            df.loc[df.index[0], mutated_column] = "CUS_mutated_after_build_0000000"
            df.to_parquet(table_path, index=False)

            with pytest.raises(RawIntegrityError, match="content_hash_mismatch"):
                verify_build_sources(manifest.sources)

            with pytest.raises(RawIntegrityError):
                run_reconciliation(Path(manifest.db_path), manifest.sources)

            with pytest.raises(RawIntegrityError):
                run_named_query(Path(manifest.db_path), "portfolio_monthly", manifest.sources)
        finally:
            table_path.write_bytes(original_bytes)

        # Restored to the original bytes - integrity holds again.
        verify_build_sources(manifest.sources)

    def test_deleting_a_source_table_is_detected(
        self, isolated_run: tuple[str, Path, Path], a_built_warehouse: str
    ) -> None:
        _run_id, _operational_root, operational_dir = isolated_run
        manifest = load_build_manifest(a_built_warehouse)

        table_path = operational_dir / "recovery_events.parquet"
        original_bytes = table_path.read_bytes()
        try:
            table_path.unlink()
            with pytest.raises(RawIntegrityError, match="missing_file"):
                verify_build_sources(manifest.sources)
        finally:
            table_path.write_bytes(original_bytes)
        verify_build_sources(manifest.sources)

    def test_adding_rows_is_detected_as_row_count_mismatch(
        self, isolated_run: tuple[str, Path, Path], a_built_warehouse: str
    ) -> None:
        _run_id, _operational_root, operational_dir = isolated_run
        manifest = load_build_manifest(a_built_warehouse)

        table_path = operational_dir / "customers.parquet"
        original_bytes = table_path.read_bytes()
        try:
            df = pd.read_parquet(table_path)
            duplicated = pd.concat([df, df.iloc[[0]]], ignore_index=True)
            duplicated.to_parquet(table_path, index=False)

            with pytest.raises(RawIntegrityError) as exc_info:
                verify_build_sources(manifest.sources)
            assert "row_count_mismatch" in str(exc_info.value) or "content_hash_mismatch" in str(
                exc_info.value
            )
        finally:
            table_path.write_bytes(original_bytes)
        verify_build_sources(manifest.sources)

    def test_editing_the_run_manifest_status_is_detected(
        self, isolated_run: tuple[str, Path, Path], a_built_warehouse: str
    ) -> None:
        import json

        _run_id, _operational_root, operational_dir = isolated_run
        manifest = load_build_manifest(a_built_warehouse)
        run_manifest_path = operational_dir.parent / "manifest.json"
        original_text = run_manifest_path.read_text(encoding="utf-8")
        try:
            payload = json.loads(original_text)
            payload["status"] = "quarantined_expected_failure"
            run_manifest_path.write_text(json.dumps(payload), encoding="utf-8")

            with pytest.raises(RawIntegrityError, match="status_changed"):
                verify_build_sources(manifest.sources)
        finally:
            run_manifest_path.write_text(original_text, encoding="utf-8")
        verify_build_sources(manifest.sources)


class TestIntegrityViolationReporting:
    def test_violation_str_includes_run_id_table_and_kind(self) -> None:
        v = IntegrityViolation("RUN_x", "customers", "row_count_mismatch", "1 vs 2")
        text = str(v)
        assert "RUN_x" in text
        assert "customers" in text
        assert "row_count_mismatch" in text

    def test_verify_build_sources_collects_every_violation_not_just_the_first(self) -> None:
        fake_sources = [
            {
                "run_id": "RUN_does_not_exist_0000",
                "source_path": "data/does/not/exist/operational",
                "generator_version": "0.0.0",
                "contract_version_set": "phase5-v1",
                "global_content_hash": "deadbeef",
                "row_counts": {"customers": 10},
            },
            {
                "run_id": "RUN_also_does_not_exist_0000",
                "source_path": "data/also/not/there/operational",
                "generator_version": "0.0.0",
                "contract_version_set": "phase5-v1",
                "global_content_hash": "deadbeef",
                "row_counts": {"customers": 10},
            },
        ]
        with pytest.raises(RawIntegrityError) as exc_info:
            verify_build_sources(fake_sources)
        message = str(exc_info.value)
        assert "RUN_does_not_exist_0000" in message
        assert "RUN_also_does_not_exist_0000" in message
