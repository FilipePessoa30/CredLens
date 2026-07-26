"""Tests for credlens.warehouse.build: a real `dbt build` invoked via
dbtRunner, its build manifest, and the idempotency/analytical-fingerprint
guarantee (Phase 5 sections 10-11: two builds from the same inputs must
produce the same counts, keys, and analytical fingerprint)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.generation.config import load_generation_config
from credlens.generation.orchestrator import generate_scenario
from credlens.warehouse.build import (
    BuildError,
    _rmtree_with_retry,
    build_dir_for,
    generate_docs,
    load_build_manifest,
    run_build,
    run_tests,
)
from credlens.warehouse.queries import NAMED_QUERIES, QueryError, run_named_query

_SEED = 615_301
_BUILD_ID_1 = "BUILD_pytest_warehouse_build_1"
_BUILD_ID_2 = "BUILD_pytest_warehouse_build_2"


@pytest.fixture(scope="module")
def a_real_run() -> Iterator[str]:
    outcome = generate_scenario(scenario="baseline", scale_name="smoke", seed=_SEED, force=True)
    yield outcome.generation_run_id
    config = load_generation_config()
    for base in (config.output.operational_dir, config.output.truth_dir):
        path = Path(base) / outcome.generation_run_id
        if path.exists():
            shutil.rmtree(path)


@pytest.fixture(scope="module")
def a_built_warehouse(a_real_run: str) -> Iterator[str]:
    manifest = run_build(run_id=a_real_run, build_id=_BUILD_ID_1, force=True)
    yield manifest.build_id
    for build_id in (_BUILD_ID_1, _BUILD_ID_2):
        build_dir = build_dir_for(build_id)
        if build_dir.exists():
            try:
                _rmtree_with_retry(build_dir)
            except PermissionError:
                # Final teardown only - a straggler dbt.log from the last
                # invocation in this process may still be locked (see
                # run_build's own comment on why dbt_logs/ is never
                # programmatically deleted mid-session). Harmless: this
                # whole tree is gitignored, ephemeral test output.
                shutil.rmtree(build_dir, ignore_errors=True)


class TestRunBuild:
    def test_build_succeeds_with_all_tests_passing(self, a_built_warehouse: str) -> None:
        manifest = load_build_manifest(a_built_warehouse)
        assert manifest.final_status == "success"
        assert manifest.test_results["failed"] == 0
        assert manifest.test_results["errored"] == 0
        assert manifest.test_results["passed"] > 0

    def test_manifest_has_required_audit_fields(self, a_built_warehouse: str) -> None:
        manifest = load_build_manifest(a_built_warehouse)
        assert manifest.build_id == a_built_warehouse
        assert Path(manifest.db_path).is_file()
        assert manifest.included_run_ids
        assert manifest.code_version
        assert manifest.dbt_version
        assert manifest.duckdb_version
        assert manifest.sources
        assert manifest.raw_row_counts
        assert manifest.model_row_counts
        assert manifest.analytical_fingerprint
        assert manifest.step_durations["total"] > 0

    def test_analytical_fingerprint_is_not_a_file_hash(self, a_built_warehouse: str) -> None:
        # The fingerprint must be a content+metadata+count hash, not the raw
        # .duckdb binary hash - assert it does NOT equal the file's own hash.
        import hashlib

        manifest = load_build_manifest(a_built_warehouse)
        file_hash = hashlib.sha256(Path(manifest.db_path).read_bytes()).hexdigest()
        assert manifest.analytical_fingerprint != file_hash

    def test_destination_exists_without_force_raises(
        self, a_real_run: str, a_built_warehouse: str
    ) -> None:
        with pytest.raises(BuildError, match="already exists"):
            run_build(run_id=a_real_run, build_id=a_built_warehouse, force=False)

    def test_unknown_build_id_status_raises(self) -> None:
        with pytest.raises(BuildError, match="No build found"):
            load_build_manifest("BUILD_does_not_exist_0000")


class TestIdempotency:
    def test_two_builds_from_same_run_produce_same_fingerprint(self, a_real_run: str) -> None:
        first = run_build(run_id=a_real_run, build_id=_BUILD_ID_1, force=True)
        second = run_build(run_id=a_real_run, build_id=_BUILD_ID_2, force=True)

        assert first.analytical_fingerprint == second.analytical_fingerprint
        assert first.model_row_counts == second.model_row_counts
        assert first.included_run_ids == second.included_run_ids


class TestRunTests:
    def test_rerun_tests_without_rebuild_succeeds(self, a_built_warehouse: str) -> None:
        results = run_tests(a_built_warehouse)
        assert results["success"] is True
        assert results["failed"] == 0
        assert results["errored"] == 0


class TestGenerateDocs:
    def test_docs_generated(self, a_built_warehouse: str) -> None:
        index_path = generate_docs(a_built_warehouse)
        assert index_path.is_file()


class TestNamedQueries:
    @pytest.mark.parametrize("name", sorted(NAMED_QUERIES))
    def test_every_named_query_runs(self, a_built_warehouse: str, name: str) -> None:
        manifest = load_build_manifest(a_built_warehouse)
        columns, rows = run_named_query(Path(manifest.db_path), name, manifest.sources)
        assert columns
        # A single baseline run has no scenario to compare against, so
        # scenario_comparison legitimately returns 0 rows - every other
        # named query must return at least one row for a real baseline run.
        if name != "scenario_comparison":
            assert len(rows) > 0

    def test_unknown_query_name_raises(self, a_built_warehouse: str) -> None:
        manifest = load_build_manifest(a_built_warehouse)
        with pytest.raises(QueryError, match="Unknown query name"):
            run_named_query(Path(manifest.db_path), "not_a_real_query", manifest.sources)

    def test_missing_database_raises(self) -> None:
        missing_db = Path("data/warehouse/does_not_exist/warehouse.duckdb")
        with pytest.raises(QueryError, match="No database file"):
            run_named_query(missing_db, "portfolio_monthly", [])
