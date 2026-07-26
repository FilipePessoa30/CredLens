"""Warehouse build orchestration (Phase 5, sections 9-11 of the phase brief).

Resolves safe sources (`credlens.warehouse.sources.resolve_sources`),
invokes dbt programmatically via dbt-core's own `dbtRunner` (no subprocess,
no stdout scraping - the same API Airflow/Dagster providers use), and writes
a build manifest recording everything needed to audit or reproduce the
build: included runs, code/dbt/DuckDB versions, source hashes, row counts,
test results, step durations, and an *analytical fingerprint*.

The analytical fingerprint is deliberately NOT a hash of the `.duckdb`
binary file (DuckDB's on-disk layout is not guaranteed byte-identical
across otherwise-equivalent rebuilds - free-space layout, checkpoint
timing, etc. can differ). Instead it is computed from ordered *content* of
every physically materialized table (dimensions/facts/marts - raw/staging/
intermediate are views, not build artifacts) plus build metadata, so two
builds from the same inputs must produce the same fingerprint even if the
underlying files differ byte-for-byte. See docs/warehouse_architecture.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from credlens import __version__ as credlens_version
from credlens.warehouse.sources import SourceRecord, resolve_sources

WAREHOUSE_PROJECT_DIR = Path("warehouse")
BUILD_ROOT = Path("data/warehouse")


class BuildError(Exception):
    """Raised when a warehouse build cannot proceed, or dbt itself failed."""


@dataclass(frozen=True)
class BuildManifest:
    """Everything Phase 5 section 11 requires a build's own audit trail to record."""

    build_id: str
    db_path: str
    run_id: str | None
    suite_id: str | None
    included_run_ids: list[str]
    code_version: str
    dbt_version: str
    duckdb_version: str
    sources: list[dict[str, Any]]
    raw_row_counts: dict[str, dict[str, int]]
    model_row_counts: dict[str, int]
    test_results: dict[str, Any]
    step_durations: dict[str, float]
    analytical_fingerprint: str
    final_status: str
    built_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "build_id": self.build_id,
            "db_path": self.db_path,
            "run_id": self.run_id,
            "suite_id": self.suite_id,
            "included_run_ids": self.included_run_ids,
            "code_version": self.code_version,
            "dbt_version": self.dbt_version,
            "duckdb_version": self.duckdb_version,
            "sources": self.sources,
            "raw_row_counts": self.raw_row_counts,
            "model_row_counts": self.model_row_counts,
            "test_results": self.test_results,
            "step_durations": self.step_durations,
            "analytical_fingerprint": self.analytical_fingerprint,
            "final_status": self.final_status,
            "built_at": self.built_at,
        }


def _rmtree_with_retry(
    path: Path, *, attempts: int = 5, initial_delay_seconds: float = 0.2
) -> None:
    """shutil.rmtree with short exponential backoff. DuckDB/dbt-duckdb
    release their OS-level file handle asynchronously relative to
    reset_adapters()/close_all_connections()/gc.collect() returning (a
    background thread finalizes the handle slightly after the Python
    object is dereferenced) - on Windows this occasionally makes an
    immediately-following rmtree() of that same build directory hit a
    transient PermissionError/WinError32, even though the same file is
    reliably deletable a few hundred milliseconds later. This is the
    standard mitigation for that class of race (the same pattern pip and
    git use for Windows file-lock flakiness), not a fix for a specific
    known-broken code path."""
    delay = initial_delay_seconds
    for attempt in range(1, attempts + 1):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if attempt == attempts:
                raise
            time.sleep(delay)
            delay *= 2


def _new_log_path(target_dir: Path) -> Path:
    """A fresh, never-reused log subdirectory for one dbt invocation - see
    _rmtree_with_retry's neighboring comment in run_build for why this
    exists instead of one fixed dbt_logs/ path per build."""
    return target_dir / "dbt_logs" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def build_dir_for(build_id: str) -> Path:
    return BUILD_ROOT / build_id


def load_build_manifest(build_id: str) -> BuildManifest:
    manifest_path = build_dir_for(build_id) / "build_manifest.json"
    if not manifest_path.is_file():
        raise BuildError(
            f"No build found with build_id '{build_id}' (looked at '{manifest_path}')."
        )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return BuildManifest(**payload)


def _build_id_for(run_id: str | None, suite_id: str | None) -> str:
    scope = run_id if run_id is not None else suite_id
    assert scope is not None
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"BUILD_{scope}_{timestamp}"


def _render_profiles_yml() -> None:
    example = WAREHOUSE_PROJECT_DIR / "profiles.example.yml"
    target = WAREHOUSE_PROJECT_DIR / "profiles.yml"
    target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")


def _dbt_version() -> str:
    import dbt.version

    return str(dbt.version.installed)


def _duckdb_version() -> str:
    import duckdb

    return str(duckdb.__version__)


def _invoke_dbt(
    command: list[str], target_path: Path, log_path: Path, vars_json: str, *, quiet: bool = False
) -> Any:
    from dbt.cli.main import dbtRunner

    runner = dbtRunner()
    # dbt resolves --target-path/--log-path RELATIVE TO --project-dir, not
    # the process cwd - passing them as relative paths silently nested a
    # stray warehouse/data/warehouse/... tree inside the dbt project dir
    # during development. Absolute paths for every path flag avoid that
    # regardless of the caller's cwd or --project-dir's own relativity.
    args = [
        *command,
        "--profiles-dir",
        str(WAREHOUSE_PROJECT_DIR.resolve()),
        "--project-dir",
        str(WAREHOUSE_PROJECT_DIR.resolve()),
        "--target-path",
        str(target_path.resolve()),
        "--log-path",
        str(log_path.resolve()),
        "--vars",
        vars_json,
    ]
    if quiet:
        # dbt otherwise prints its own progress lines straight to stdout
        # (independent of --log-path, which only affects the file log) -
        # --quiet suppresses those so a caller requesting --json gets
        # stdout that is pure, parseable JSON and nothing else.
        args.append("--quiet")
    result = runner.invoke(args)

    # dbtRunner is designed for long-lived CLI/server processes and keeps
    # several things open across invoke() calls within the same process:
    # the adapter registry, dbt's own file logger (--log-path/dbt.log),
    # and - specific to dbt-duckdb - a class-level cached Environment
    # holding the actual DuckDB connection
    # (dbt.adapters.duckdb.connections.DuckDBConnectionManager._ENV),
    # which reset_adapters() does NOT touch (it lives outside dbt-core's
    # own adapter-factory registry). Left open, all of this stays locked -
    # merely inconvenient on Linux but a hard PermissionError on Windows
    # for any subsequent open() of the same files, which this module does
    # repeatedly within one process (build -> read-back for the analytical
    # fingerprint, and two back-to-back builds when proving idempotency).
    # Each call below is a documented/public release point for its own
    # layer; gc.collect() ensures the now-dereferenced DuckDB connection
    # object is actually finalized (closing its OS file handle) rather
    # than left for an arbitrary future GC cycle.
    import gc

    from dbt.adapters.factory import reset_adapters
    from dbt.events.logging import cleanup_event_logger  # type: ignore[attr-defined]

    # dbt-core's own release functions are not fully type-annotated
    # (no-untyped-call) - an external-library gap, not a typing error in
    # this module.
    reset_adapters()  # type: ignore[no-untyped-call]
    cleanup_event_logger()
    try:
        from dbt.adapters.duckdb.connections import DuckDBConnectionManager

        DuckDBConnectionManager.close_all_connections()  # type: ignore[no-untyped-call]
    except ImportError:  # pragma: no cover - only if dbt-duckdb isn't the adapter in use
        pass
    gc.collect()

    return result


def _extract_test_results(dbt_run_result: Any) -> dict[str, Any]:
    passed = failed = errored = skipped = 0
    failures: list[str] = []
    node_results = getattr(dbt_run_result, "results", None) or []
    for node_result in node_results:
        node = getattr(node_result, "node", None)
        resource_type = str(getattr(node, "resource_type", ""))
        if "test" not in resource_type.lower():
            continue
        status = str(getattr(node_result, "status", ""))
        name = getattr(node, "name", "unknown")
        if status in ("pass", "success"):
            passed += 1
        elif status == "skipped":
            skipped += 1
        elif status == "fail":
            failed += 1
            failures.append(name)
        else:
            errored += 1
            failures.append(name)
    return {
        "passed": passed,
        "failed": failed,
        "errored": errored,
        "skipped": skipped,
        "failures": failures,
    }


# Physical schemas fingerprinted - matched by suffix because dbt-duckdb
# prefixes the configured `+schema:` with the target's default schema
# (observed as "main_dimensions"/"main_facts"/"main_marts" - see
# profiles.example.yml's single `dev` target). raw/staging/intermediate are
# views re-evaluated from source parquet on every query, not build
# artifacts, so they are deliberately excluded from the fingerprint.
_FINGERPRINTED_SCHEMA_SUFFIXES = ("dimensions", "facts", "marts")


def _table_fingerprint(conn: Any, schema: str, table: str) -> tuple[int, str]:
    row_count = conn.execute(f'select count(*) from "{schema}"."{table}"').fetchone()[0]
    if row_count == 0:
        return 0, hashlib.sha256(b"").hexdigest()
    result = conn.execute(
        f"select md5(string_agg(row_str, '' order by row_str)) "
        f'from (select (t)::varchar as row_str from "{schema}"."{table}" as t) as rows'
    ).fetchone()
    return int(row_count), str(result[0])


def compute_analytical_fingerprint(
    db_path: Path, sources: list[SourceRecord]
) -> tuple[str, dict[str, int]]:
    """Content+metadata+count based fingerprint - NEVER the .duckdb binary hash."""
    import duckdb

    # NOT read_only=True: DuckDB's Python driver caches one in-process
    # connection per database file path, and dbt-duckdb's own adapter
    # connection (opened read-write during `dbt build`) may still be alive
    # in this same process when this runs immediately afterward - opening
    # a second connection to the same file with a *different* configuration
    # (read_only vs read-write) raises ConnectionException. Matching dbt's
    # own read-write configuration lets DuckDB safely reuse that connection.
    conn = duckdb.connect(str(db_path))
    try:
        like_clauses = " or ".join("table_schema like ?" for _ in _FINGERPRINTED_SCHEMA_SUFFIXES)
        params = [f"%{suffix}" for suffix in _FINGERPRINTED_SCHEMA_SUFFIXES]
        table_rows = conn.execute(
            f"select table_schema, table_name from information_schema.tables "
            f"where {like_clauses} order by table_schema, table_name",
            params,
        ).fetchall()

        model_row_counts: dict[str, int] = {}
        content_parts: list[str] = []
        for schema, table in table_rows:
            row_count, content_hash = _table_fingerprint(conn, schema, table)
            model_row_counts[f"{schema}.{table}"] = row_count
            content_parts.append(f"{schema}.{table}:{row_count}:{content_hash}")
    finally:
        conn.close()

    metadata_parts = sorted(f"{s.run_id}:{s.global_content_hash}" for s in sources)
    payload = "\n".join(sorted(content_parts)) + "\n---\n" + "\n".join(metadata_parts)
    fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return fingerprint, model_row_counts


def run_build(
    *,
    run_id: str | None = None,
    suite_id: str | None = None,
    build_id: str | None = None,
    force: bool = False,
    quiet: bool = False,
) -> BuildManifest:
    """Resolve sources, run `dbt build`, and write a build manifest. Raises
    BuildError/SourceSelectionError - never returns a partial or silently
    downgraded result."""
    t_start_total = time.perf_counter()
    step_durations: dict[str, float] = {}

    t0 = time.perf_counter()
    sources = resolve_sources(run_id=run_id, suite_id=suite_id)
    step_durations["resolve_sources"] = time.perf_counter() - t0

    resolved_build_id = build_id or _build_id_for(run_id, suite_id)
    target_dir = build_dir_for(resolved_build_id)
    db_path = target_dir / "warehouse.duckdb"
    dbt_target_path = target_dir / "dbt_target"

    if db_path.exists() or (target_dir / "build_manifest.json").exists():
        if not force:
            raise BuildError(
                f"Build destination '{target_dir}' already exists. Pass force=True "
                "(CLI: --force) to overwrite it, or omit --build-id to let one be "
                "generated automatically."
            )
        # Only the database file (+ its WAL sibling, if checkpointing left
        # one) and dbt's own compiled artifacts dir are removed - NOT
        # dbt_logs/. dbt-duckdb's cached Environment releases its DuckDB
        # connection reliably (DuckDBConnectionManager.close_all_connections()
        # + gc.collect(), below) but dbt's own event-log file handle does
        # not release deterministically within one process even after every
        # documented cleanup call - see the two BUILD_pytest_* runs compared
        # while diagnosing this. Rather than delete-and-recreate a file that
        # may still be locked by dbt's own prior invocation, every dbt
        # invocation gets its own timestamped log subdirectory (below), so
        # old logs are simply left in place (harmless - tiny text files,
        # gitignored like the rest of data/warehouse/) instead of ever being
        # deleted while still open.
        for stale in (db_path, db_path.with_suffix(".duckdb.wal")):
            if stale.exists():
                stale.unlink()
        if dbt_target_path.exists():
            _rmtree_with_retry(dbt_target_path)
    target_dir.mkdir(parents=True, exist_ok=True)

    dbt_log_path = _new_log_path(target_dir)

    _render_profiles_yml()
    os.environ["CREDLENS_WAREHOUSE_DB_PATH"] = str(db_path)

    vars_json = json.dumps({"selected_runs": [s.to_dict() for s in sources]})

    t0 = time.perf_counter()
    dbt_result = _invoke_dbt(["build"], dbt_target_path, dbt_log_path, vars_json, quiet=quiet)
    step_durations["dbt_build"] = time.perf_counter() - t0

    success = bool(getattr(dbt_result, "success", False))
    test_results = _extract_test_results(getattr(dbt_result, "result", None))
    final_status = "success" if success else "failed"

    analytical_fingerprint = ""
    model_row_counts: dict[str, int] = {}
    if success:
        t0 = time.perf_counter()
        analytical_fingerprint, model_row_counts = compute_analytical_fingerprint(db_path, sources)
        step_durations["analytical_fingerprint"] = time.perf_counter() - t0

    step_durations["total"] = time.perf_counter() - t_start_total

    manifest = BuildManifest(
        build_id=resolved_build_id,
        db_path=str(db_path),
        run_id=run_id,
        suite_id=suite_id,
        included_run_ids=[s.run_id for s in sources],
        code_version=credlens_version,
        dbt_version=_dbt_version(),
        duckdb_version=_duckdb_version(),
        sources=[s.to_dict() for s in sources],
        raw_row_counts={s.run_id: s.row_counts for s in sources},
        model_row_counts=model_row_counts,
        test_results=test_results,
        step_durations=step_durations,
        analytical_fingerprint=analytical_fingerprint,
        final_status=final_status,
        built_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    manifest_path = target_dir / "build_manifest.json"
    manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")

    exception = getattr(dbt_result, "exception", None)
    if exception is not None:
        raise BuildError(f"dbt build raised an exception: {exception}")

    return manifest


def generate_docs(build_id: str) -> Path:
    """Runs `dbt docs generate` against an already-built database (static
    HTML/JSON site under the build's own dbt_target/ - never served here,
    only generated; `dbt docs serve` would block the CLI process)."""
    manifest = load_build_manifest(build_id)
    target_dir = build_dir_for(build_id)
    db_path = Path(manifest.db_path)
    if not db_path.is_file():
        raise BuildError(f"Build '{build_id}' has no database at '{db_path}' - was it deleted?")

    _render_profiles_yml()
    os.environ["CREDLENS_WAREHOUSE_DB_PATH"] = str(db_path)

    vars_json = json.dumps({"selected_runs": manifest.sources})
    dbt_target_path = target_dir / "dbt_target"
    dbt_log_path = _new_log_path(target_dir)

    dbt_result = _invoke_dbt(["docs", "generate"], dbt_target_path, dbt_log_path, vars_json)
    if not bool(getattr(dbt_result, "success", False)):
        exception = getattr(dbt_result, "exception", "unknown error")
        raise BuildError(f"dbt docs generate failed: {exception}")
    return dbt_target_path / "index.html"


def run_tests(build_id: str, *, quiet: bool = False) -> dict[str, Any]:
    """Re-run `dbt test` (no rebuild) against an already-built database,
    using the exact source selection recorded in that build's manifest."""
    manifest = load_build_manifest(build_id)
    target_dir = build_dir_for(build_id)
    db_path = Path(manifest.db_path)
    if not db_path.is_file():
        raise BuildError(f"Build '{build_id}' has no database at '{db_path}' - was it deleted?")

    _render_profiles_yml()
    os.environ["CREDLENS_WAREHOUSE_DB_PATH"] = str(db_path)

    vars_json = json.dumps({"selected_runs": manifest.sources})
    dbt_target_path = target_dir / "dbt_target"
    dbt_log_path = _new_log_path(target_dir)

    dbt_result = _invoke_dbt(["test"], dbt_target_path, dbt_log_path, vars_json, quiet=quiet)
    return _extract_test_results(getattr(dbt_result, "result", None)) | {
        "success": bool(getattr(dbt_result, "success", False))
    }
