"""Demo aggregate package (Phase 7 section 18) - a small, versionable
Parquet snapshot of exactly the aggregate tables the dashboard needs, so
anyone can run `credlens dashboard run --demo` without regenerating
the synthetic portfolio or building a warehouse.

Hard rules enforced here, not just documented:
  - no customer-level or contract-level row ever leaves this package -
    `cure_and_redefault` (grain: one row per contract) is re-aggregated
    into a scenario-level summary before being written; every other
    source table is already aggregate (see credlens.analysis.metrics'
    own docstrings for each table's grain).
  - no truth-layer data, no quarantine data, no raw source files, no
    credentials, no full DuckDB database.
  - a documented size budget (DEMO_PACKAGE_SIZE_BUDGET_BYTES) - checked,
    not just asserted in prose.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from credlens import __version__ as credlens_version
from credlens.analysis.data_provenance import get_table_provenance

DEMO_PACKAGE_VERSION = "1.0.0"

# 5 MiB - generous relative to this project's own tables (~1.6 MB of
# source CSVs before Parquet compression and before re-aggregating the
# one large per-contract table away), but still trivially small enough
# for ordinary GitHub versioning (GitHub itself warns above 50 MB).
DEMO_PACKAGE_SIZE_BUDGET_BYTES = 5 * 1024 * 1024

# Tables copied through as-is (already aggregate grain - see
# credlens.analysis.metrics' docstrings for each one's exact grain).
_PASSTHROUGH_TABLES: tuple[str, ...] = (
    "funnel_monthly",
    "portfolio_monthly",
    "delinquency_monthly",
    "vintage_cohorts",
    "roll_rates",
    "collections_performance",
    "writeoff_recovery",
    "scenario_comparison",
    "macro_stress_pre_post",
    "funnel_by_channel_and_scenario",
    "portfolio_by_region_and_channel",
    "policy_version_comparison",
)

# Columns that would identify an individual contract/customer - a demo
# table must never carry any of these (checked both at build time here
# and at validation time in `validate_demo_package`).
_FORBIDDEN_COLUMNS = frozenset(
    {"contract_key", "contract_id", "customer_key", "customer_id", "application_id"}
)


class DemoPackageError(Exception):
    """Raised when the demo package cannot be built or fails validation."""


@dataclass(frozen=True)
class DemoTableRecord:
    name: str
    row_count: int
    sha256: str
    provenance: str
    size_bytes: int


@dataclass(frozen=True)
class DemoManifest:
    demo_package_version: str
    source_build_id: str
    source_analysis_id: str | None
    warehouse_fingerprint: str
    package_version: str
    generated_at: str
    tables: dict[str, DemoTableRecord]
    insights_included: bool
    total_size_bytes: int
    limitations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "demo_package_version": self.demo_package_version,
            "source_build_id": self.source_build_id,
            "source_analysis_id": self.source_analysis_id,
            "warehouse_fingerprint": self.warehouse_fingerprint,
            "package_version": self.package_version,
            "generated_at": self.generated_at,
            "tables": {
                name: {
                    "row_count": t.row_count,
                    "sha256": t.sha256,
                    "provenance": t.provenance,
                    "size_bytes": t.size_bytes,
                }
                for name, t in self.tables.items()
            },
            "insights_included": self.insights_included,
            "total_size_bytes": self.total_size_bytes,
            "limitations": self.limitations,
        }


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _aggregate_cure_and_redefault(df: pd.DataFrame) -> pd.DataFrame:
    """Collapses the per-contract cure_and_redefault table (grain:
    run_id x contract_key) into a scenario-level summary - the ONLY
    source table whose native grain is contract-level, so the ONLY one
    that needs re-aggregation before it may enter the demo package."""
    if df.empty:
        return pd.DataFrame(
            columns=[
                "run_id",
                "suite_id",
                "scenario",
                "n_contracts",
                "n_ever_cured",
                "n_redefaulted",
                "cure_incidence",
                "redefault_rate",
            ]
        )
    grouped = df.groupby(["run_id", "suite_id", "scenario"], as_index=False).agg(
        n_contracts=("contract_key", "count"),
        n_ever_cured=("was_ever_cured", "sum"),
        n_redefaulted=("redefaulted", "sum"),
    )
    grouped["cure_incidence"] = grouped["n_ever_cured"] / grouped["n_contracts"].replace(0, pd.NA)
    grouped["redefault_rate"] = grouped["n_redefaulted"] / grouped["n_ever_cured"].replace(0, pd.NA)
    return grouped


def build_demo_package(
    *,
    analysis_output_dir: Path,
    output_dir: Path,
    db_path: Path | None = None,
    suite_id: str | None = None,
) -> DemoManifest:
    """Builds the demo package primarily from an already-validated
    `credlens analysis run` output directory (its CSVs), so the demo
    package can never accidentally carry more than what that run already
    wrote. `db_path`/`suite_id`, if given, additionally include the
    dashboard-only `credit_risk_segment_summary` table (not part of the
    standard `analysis run` table set) by querying the SAME validated,
    read-only build - kept optional so a demo package can still be built
    from just an analysis output directory with no warehouse available."""
    manifest_path = analysis_output_dir / "manifest.json"
    if not manifest_path.is_file():
        raise DemoPackageError(
            f"No analysis manifest at '{manifest_path}' - run `credlens analysis run` first."
        )
    analysis_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tables_dir = analysis_output_dir / "tables"

    output_dir.mkdir(parents=True, exist_ok=True)
    tables: dict[str, DemoTableRecord] = {}

    def _write_parquet(name: str, df: pd.DataFrame) -> None:
        forbidden_present = _FORBIDDEN_COLUMNS & set(df.columns)
        if forbidden_present:
            raise DemoPackageError(
                f"Refusing to include table '{name}' in the demo package - it carries "
                f"contract/customer-identifying column(s) {sorted(forbidden_present)}."
            )
        out_path = output_dir / f"{name}.parquet"
        df.to_parquet(out_path, index=False, compression="zstd")
        provenance = (
            get_table_provenance(name).category
            if name in _PASSTHROUGH_TABLES
            else ("synthetic_scenario")
        )
        tables[name] = DemoTableRecord(
            name=name,
            row_count=len(df),
            sha256=_file_sha256(out_path),
            provenance=provenance,
            size_bytes=out_path.stat().st_size,
        )

    for name in _PASSTHROUGH_TABLES:
        csv_path = tables_dir / f"{name}.csv"
        if not csv_path.is_file():
            continue
        _write_parquet(name, pd.read_csv(csv_path))

    cure_path = tables_dir / "cure_and_redefault.csv"
    if cure_path.is_file():
        summary = _aggregate_cure_and_redefault(pd.read_csv(cure_path))
        _write_parquet("cure_redefault_summary", summary)

    if db_path is not None and suite_id is not None:
        from credlens.analysis import metrics as analysis_metrics

        with analysis_metrics.connect(db_path) as conn:
            segment_df = analysis_metrics.credit_risk_segment_summary(conn, suite_id)
        _write_parquet("credit_risk_segment_summary", segment_df)

    insights_included = False
    insights_src = analysis_output_dir / "insights.yml"
    if insights_src.is_file():
        insights_dst = output_dir / "insights.yml"
        insights_dst.write_text(insights_src.read_text(encoding="utf-8"), encoding="utf-8")
        insights_included = True

    total_size = sum(t.size_bytes for t in tables.values())
    if insights_included:
        total_size += (output_dir / "insights.yml").stat().st_size
    if total_size > DEMO_PACKAGE_SIZE_BUDGET_BYTES:
        raise DemoPackageError(
            f"Demo package size {total_size:,} bytes exceeds the "
            f"{DEMO_PACKAGE_SIZE_BUDGET_BYTES:,}-byte budget - see "
            "credlens.dashboard.demo_package.DEMO_PACKAGE_SIZE_BUDGET_BYTES."
        )

    manifest = DemoManifest(
        demo_package_version=DEMO_PACKAGE_VERSION,
        source_build_id=analysis_manifest["build_id"],
        source_analysis_id=analysis_manifest.get("analysis_id"),
        warehouse_fingerprint=analysis_manifest["warehouse_fingerprint"],
        package_version=credlens_version,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        tables=tables,
        insights_included=insights_included,
        total_size_bytes=total_size,
        limitations=[
            "Aggregate tables only - no customer-level, contract-level, or truth-layer data.",
            "cure_and_redefault was re-aggregated from contract grain to a scenario summary.",
            "Synthetic data only where scenario/suite-scoped - see each table's own provenance.",
        ],
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest


def load_demo_manifest(demo_data_dir: Path) -> DemoManifest:
    manifest_path = demo_data_dir / "manifest.json"
    if not manifest_path.is_file():
        raise DemoPackageError(f"No demo package manifest at '{manifest_path}'.")
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    tables = {
        name: DemoTableRecord(
            name=name,
            row_count=t["row_count"],
            sha256=t["sha256"],
            provenance=t["provenance"],
            size_bytes=t["size_bytes"],
        )
        for name, t in raw["tables"].items()
    }
    return DemoManifest(
        demo_package_version=raw["demo_package_version"],
        source_build_id=raw["source_build_id"],
        source_analysis_id=raw.get("source_analysis_id"),
        warehouse_fingerprint=raw["warehouse_fingerprint"],
        package_version=raw["package_version"],
        generated_at=raw["generated_at"],
        tables=tables,
        insights_included=raw["insights_included"],
        total_size_bytes=raw["total_size_bytes"],
        limitations=raw["limitations"],
    )


def validate_demo_package(demo_data_dir: Path) -> DemoManifest:
    """Re-verifies every table's hash against the manifest (tamper
    detection - Phase 7 section 18.4) and refuses any forbidden column."""
    manifest = load_demo_manifest(demo_data_dir)
    for name, record in manifest.tables.items():
        path = demo_data_dir / f"{name}.parquet"
        if not path.is_file():
            raise DemoPackageError(f"Demo table '{name}' is missing at '{path}'.")
        actual_hash = _file_sha256(path)
        if actual_hash != record.sha256:
            raise DemoPackageError(
                f"Demo table '{name}' failed integrity verification - hash "
                f"{actual_hash[:16]}... does not match the manifest's {record.sha256[:16]}... "
                "(the file may have been tampered with or corrupted)."
            )
        columns = set(pd.read_parquet(path, columns=None).columns)
        forbidden_present = _FORBIDDEN_COLUMNS & columns
        if forbidden_present:
            raise DemoPackageError(
                f"Demo table '{name}' carries forbidden column(s) {sorted(forbidden_present)} - "
                "refusing to treat this package as valid."
            )
    return manifest
