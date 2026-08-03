"""Tests for credlens.warehouse.build: a real `dbt build` invoked via
dbtRunner, its build manifest, and the idempotency/analytical-fingerprint
guarantee (Phase 5 sections 10-11: two builds from the same inputs must
produce the same counts, keys, and analytical fingerprint)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.generation.config import load_generation_config
from credlens.generation.orchestrator import generate_scenario
from credlens.warehouse import build as build_module
from credlens.warehouse.build import (
    BuildError,
    _extract_test_results,
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


class TestExtractTestResults:
    """Fase 10C priority 1 - `_extract_test_results` branch coverage
    (skipped/fail/errored classifications a real, all-green build never
    exercises)."""

    @staticmethod
    def _node_result(resource_type: str, status: str, name: str) -> object:
        node = type("Node", (), {"resource_type": resource_type, "name": name})()
        return type("NodeResult", (), {"node": node, "status": status})()

    def test_skipped_test_is_counted_not_misclassified(self) -> None:
        dbt_run_result = type(
            "Result", (), {"results": [self._node_result("test", "skipped", "t_skipped")]}
        )()
        counts = _extract_test_results(dbt_run_result)
        assert counts == {"passed": 0, "failed": 0, "errored": 0, "skipped": 1, "failures": []}

    def test_failed_test_is_counted_and_named(self) -> None:
        dbt_run_result = type(
            "Result", (), {"results": [self._node_result("test", "fail", "t_failed")]}
        )()
        counts = _extract_test_results(dbt_run_result)
        assert counts["failed"] == 1
        assert counts["failures"] == ["t_failed"]

    def test_errored_test_is_counted_and_named(self) -> None:
        dbt_run_result = type(
            "Result", (), {"results": [self._node_result("test", "error", "t_errored")]}
        )()
        counts = _extract_test_results(dbt_run_result)
        assert counts["errored"] == 1
        assert counts["failures"] == ["t_errored"]

    def test_non_test_nodes_are_ignored(self) -> None:
        dbt_run_result = type(
            "Result", (), {"results": [self._node_result("model", "success", "m_x")]}
        )()
        counts = _extract_test_results(dbt_run_result)
        assert counts == {"passed": 0, "failed": 0, "errored": 0, "skipped": 0, "failures": []}

    def test_none_result_produces_all_zero_counts(self) -> None:
        assert _extract_test_results(None) == {
            "passed": 0,
            "failed": 0,
            "errored": 0,
            "skipped": 0,
            "failures": [],
        }


class TestBuildIdGeneration:
    def test_build_id_uses_run_id_when_both_given(self) -> None:
        build_id = build_module._build_id_for("RUN_x", "SUITE_y")
        assert build_id.startswith("BUILD_RUN_x_")

    def test_build_id_uses_suite_id_when_no_run_id(self) -> None:
        build_id = build_module._build_id_for(None, "SUITE_y")
        assert build_id.startswith("BUILD_SUITE_y_")


class TestBuildErrorPathsOnMissingDatabase:
    """Fase 10C priority 1 - `generate_docs`/`run_tests` against a build
    whose manifest exists but whose `.duckdb` file was deleted after the
    fact ("was it deleted?" - a real, if rare, operational state), using
    an isolated `BUILD_ROOT` (monkeypatched, never the real `data/
    warehouse/`) so no orphaned directory is ever left behind."""

    @pytest.fixture
    def isolated_build_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setattr(build_module, "BUILD_ROOT", tmp_path)
        return tmp_path

    def _write_manifest_with_missing_db(self, isolated_build_root: Path, build_id: str) -> None:
        build_dir = isolated_build_root / build_id
        build_dir.mkdir(parents=True)
        manifest = {
            "build_id": build_id,
            "db_path": str(build_dir / "warehouse.duckdb"),  # never created
            "run_id": "RUN_never_built",
            "suite_id": None,
            "included_run_ids": ["RUN_never_built"],
            "code_version": "0.0.0",
            "dbt_version": "0.0.0",
            "duckdb_version": "0.0.0",
            "sources": [],
            "raw_row_counts": {},
            "model_row_counts": {},
            "test_results": {"passed": 0, "failed": 0, "errored": 0, "skipped": 0, "failures": []},
            "step_durations": {"total": 0.0},
            "analytical_fingerprint": "deadbeef",
            "final_status": "success",
            "built_at": "2026-01-01T00:00:00Z",
        }
        (build_dir / "build_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_generate_docs_raises_when_database_missing(self, isolated_build_root: Path) -> None:
        self._write_manifest_with_missing_db(isolated_build_root, "BUILD_no_db_docs")
        with pytest.raises(BuildError, match="was it deleted"):
            generate_docs("BUILD_no_db_docs")

    def test_run_tests_raises_when_database_missing(self, isolated_build_root: Path) -> None:
        self._write_manifest_with_missing_db(isolated_build_root, "BUILD_no_db_tests")
        with pytest.raises(BuildError, match="was it deleted"):
            run_tests("BUILD_no_db_tests")


class TestRunBuildRaisesOnDbtException:
    """Fase 10C priority 1 - `run_build` must surface a genuine dbt-
    internal exception (as opposed to an ordinary failed test, which is
    recorded in the manifest without raising) as a `BuildError`, AFTER
    still writing the manifest for the failed attempt. A real dbt
    exception is hard to provoke deterministically, so `_invoke_dbt`
    (an external-process boundary) is stubbed here - one of only two
    mocks in this test file, per Fase 10C section 4's own allowance."""

    def test_dbt_exception_raises_buildstate_after_writing_manifest(
        self, a_real_run: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(build_module, "BUILD_ROOT", tmp_path)

        stub_result = type(
            "DbtResult",
            (),
            {"success": False, "result": None, "exception": RuntimeError("simulated dbt crash")},
        )()
        monkeypatch.setattr(build_module, "_invoke_dbt", lambda *a, **k: stub_result)

        build_id = "BUILD_dbt_exception_sim"
        with pytest.raises(BuildError, match="dbt build raised an exception"):
            run_build(run_id=a_real_run, build_id=build_id, force=True)

        # The manifest for the failed attempt must still have been written
        # BEFORE the exception was raised - an operator inspecting a
        # crashed build can still see what was attempted.
        manifest = load_build_manifest(build_id)
        assert manifest.final_status == "failed"


class TestQuietModePassesTheDbtFlag:
    """Fase 10C priority 1 - `--quiet` (`run_build(..., quiet=True)`) is
    real, working functionality no existing test exercised - a real
    build run with `quiet=True`, cleaned up afterward."""

    def test_quiet_build_still_succeeds(self, a_real_run: str) -> None:
        build_id = "BUILD_pytest_quiet_mode"
        try:
            manifest = run_build(run_id=a_real_run, build_id=build_id, force=True, quiet=True)
            assert manifest.final_status == "success"
        finally:
            build_dir = build_dir_for(build_id)
            if build_dir.exists():
                try:
                    _rmtree_with_retry(build_dir)
                except PermissionError:
                    # Same straggler dbt.log caveat as `a_built_warehouse`'s
                    # own teardown - harmless, gitignored, ephemeral.
                    shutil.rmtree(build_dir, ignore_errors=True)


class TestGenerateDocsRaisesOnDbtFailure:
    """Fase 10C priority 1 - `generate_docs` must surface a `dbt docs
    generate` failure (`success=False`, no exception raised, e.g. a real
    dbt-internal doc-rendering error) as a `BuildError` naming the
    underlying exception/reason. Hard to provoke deterministically from
    a real dbt invocation, so `_invoke_dbt` is stubbed - the database
    file itself is real (`a_built_warehouse`), so this exercises only the
    result-handling branch, not a fabricated database state."""

    def test_docs_generation_failure_raises(
        self, a_built_warehouse: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub_result = type(
            "DbtResult", (), {"success": False, "exception": "simulated docs-generate failure"}
        )()
        monkeypatch.setattr(build_module, "_invoke_dbt", lambda *a, **k: stub_result)

        with pytest.raises(BuildError, match="dbt docs generate failed"):
            generate_docs(a_built_warehouse)
