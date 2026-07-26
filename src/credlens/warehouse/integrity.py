"""Raw source integrity verification (Phase 6 gate C).

The warehouse's raw layer is materialized as DuckDB VIEWS over external
parquet files (`docs/warehouse_architecture.md`'s "Raw Materialization
Trade-off" - the architectural decision this module completes). A view
means a build's raw tables always reflect whatever is CURRENTLY on disk
at query time, not a frozen snapshot taken when the build ran - so a file
changed (or replaced, or corrupted) after a build finished would silently
change what every query downstream of that build sees, with nothing in
the build's own manifest or fingerprint ever having been wrong.

Chosen architecture (Phase 6 gate C section 6.2): **external views with
mandatory verification**, not immutable materialization. Immutable
materialization (copying every source table into the DuckDB file at
build time) was considered and rejected for this phase: it would
duplicate storage for every build sharing the same source runs, add a
real "am I stale relative to the source" question of its own once a run
gets regenerated, and buys reproducibility this project already gets a
different way - the build's own analytical fingerprint plus the
generator's own canonical per-table content hash. Views stay simple,
auditable (every query is transparently "what does the parquet say
today"), and the trade-off this decision accepts - mutability - is
addressed here directly instead of being ignored: every one of
`credlens warehouse reconcile`, `query`, and the analysis layer's own
entry points calls `verify_build_sources()` first and refuses to proceed
on any mismatch, so "the warehouse is technically mutable" never becomes
"and nobody would notice."

What is re-verified, matching Phase 6 gate C section 6.1 exactly:
existence of every source file; file size; content hash (the generator's
own `canonical_table_hash`, recomputed - not a network/IO-cheap
approximation); the expected table count for each source run; the run's
own manifest.json (status, validation_passed); contract_version_set;
generator_version.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from credlens.generation.manifest import canonical_table_hash


class RawIntegrityError(Exception):
    """Raised when a build's recorded sources no longer match the
    current state of their source parquet files/manifests - blocks
    analysis, reconciliation, named queries, and report generation."""


@dataclass(frozen=True)
class IntegrityViolation:
    run_id: str
    table: str
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.run_id}/{self.table}] {self.kind}: {self.detail}"


def _check_one_source(source: dict[str, Any]) -> list[IntegrityViolation]:
    run_id = str(source["run_id"])
    operational_dir = Path(str(source["source_path"]))
    run_dir = operational_dir.parent
    run_manifest_path = run_dir / "manifest.json"
    violations: list[IntegrityViolation] = []

    if not run_manifest_path.is_file():
        return [
            IntegrityViolation(
                run_id, "*", "missing_manifest", f"'{run_manifest_path}' no longer exists."
            )
        ]

    try:
        current_manifest: dict[str, Any] = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [
            IntegrityViolation(run_id, "*", "unreadable_manifest", f"'{run_manifest_path}': {exc}")
        ]

    if current_manifest.get("status") != "completed":
        violations.append(
            IntegrityViolation(
                run_id,
                "*",
                "status_changed",
                f"manifest now reports status={current_manifest.get('status')!r}, "
                "expected 'completed'.",
            )
        )
    if current_manifest.get("validation_passed") is not True:
        vp = current_manifest.get("validation_passed")
        violations.append(
            IntegrityViolation(
                run_id,
                "*",
                "validation_no_longer_passed",
                f"manifest now reports validation_passed={vp!r}.",
            )
        )
    if current_manifest.get("generator_version") != source.get("generator_version"):
        violations.append(
            IntegrityViolation(
                run_id,
                "*",
                "generator_version_mismatch",
                f"build recorded {source.get('generator_version')!r}, manifest now says "
                f"{current_manifest.get('generator_version')!r}.",
            )
        )
    if current_manifest.get("contract_version_set") != source.get("contract_version_set"):
        violations.append(
            IntegrityViolation(
                run_id,
                "*",
                "contract_version_set_mismatch",
                f"build recorded {source.get('contract_version_set')!r}, manifest now says "
                f"{current_manifest.get('contract_version_set')!r}.",
            )
        )
    if current_manifest.get("global_content_hash") != source.get("global_content_hash"):
        violations.append(
            IntegrityViolation(
                run_id,
                "*",
                "global_content_hash_mismatch",
                f"build recorded {source.get('global_content_hash')!r}, manifest now says "
                f"{current_manifest.get('global_content_hash')!r} - this run's data changed "
                "since the build was made.",
            )
        )

    recorded_row_counts = dict(source.get("row_counts") or {})
    current_tables: dict[str, Any] = dict(current_manifest.get("tables") or {})
    # generation_runs.parquet is excluded from manifest["tables"] by the
    # generator's own design (see credlens.warehouse.sources) - it has no
    # canonical_hash to re-check, only a file-existence/row-count check.
    expected_table_count = len(recorded_row_counts)
    actual_table_files = len(list(operational_dir.glob("*.parquet")))
    if actual_table_files < expected_table_count:
        violations.append(
            IntegrityViolation(
                run_id,
                "*",
                "table_count_mismatch",
                f"build recorded {expected_table_count} table(s), only {actual_table_files} "
                f"parquet file(s) found under '{operational_dir}'.",
            )
        )

    for table_name, recorded_count in recorded_row_counts.items():
        table_path = operational_dir / f"{table_name}.parquet"
        if not table_path.is_file():
            violations.append(
                IntegrityViolation(
                    run_id, table_name, "missing_file", f"'{table_path}' no longer exists."
                )
            )
            continue
        if table_path.stat().st_size == 0:
            violations.append(
                IntegrityViolation(run_id, table_name, "empty_file", f"'{table_path}' is 0 bytes.")
            )
            continue

        df = pd.read_parquet(table_path)
        if len(df) != recorded_count:
            violations.append(
                IntegrityViolation(
                    run_id,
                    table_name,
                    "row_count_mismatch",
                    f"build recorded {recorded_count} row(s), file now has {len(df)}.",
                )
            )

        recorded_hash = current_tables.get(table_name, {}).get("canonical_hash")
        if recorded_hash is not None:
            actual_hash = canonical_table_hash(df)
            if actual_hash != recorded_hash:
                violations.append(
                    IntegrityViolation(
                        run_id,
                        table_name,
                        "content_hash_mismatch",
                        f"manifest recorded canonical_hash={recorded_hash!r}, file content now "
                        f"hashes to {actual_hash!r} - the parquet file was modified after this "
                        "run was generated.",
                    )
                )

    return violations


def verify_build_sources(sources: list[dict[str, Any]]) -> None:
    """Re-validates every source a build recorded against the CURRENT
    state of its source parquet files and run manifest. Raises
    RawIntegrityError listing every violation found (never returns a
    partial/best-effort result) if anything no longer matches what the
    build itself recorded at build time."""
    violations: list[IntegrityViolation] = []
    for source in sources:
        violations.extend(_check_one_source(source))
    if violations:
        detail = "\n".join(f"  - {v}" for v in violations)
        raise RawIntegrityError(
            f"Raw source integrity check failed ({len(violations)} violation(s)) - refusing to "
            f"query/reconcile/report against this build:\n{detail}"
        )
