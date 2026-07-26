"""Unified, cached data access for the dashboard (Phase 7 sections 10, 15,
16). Two backends behind one interface (`load_dashboard_data`):

  - warehouse mode: opens the SAME validated build
    `credlens analysis run` would use (`validate_build_for_analysis` -
    refuses a failed build, a mutated raw source, or a missing
    fingerprint), queries it read-only via `credlens.analysis.metrics`
    (no ad hoc SQL is ever built from user input here).
  - demo mode: reads the versioned, tamper-checked Parquet package
    (`credlens.dashboard.demo_package.validate_demo_package`) - no
    `data/warehouse/` access at all.

Every cached function's key includes the build's fingerprint (warehouse)
or the demo package's own fingerprint, so switching builds/packages can
never silently keep showing stale, previously-cached data (Phase 7
section 15: "Não use cache que permita exibir dados de um build anterior
depois da selecao de outro build").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from credlens.analysis import metrics as analysis_metrics
from credlens.analysis.scenarios import composition_vs_performance
from credlens.analysis.validation import AnalysisValidationError, validate_build_for_analysis
from credlens.dashboard.config import DashboardConfig
from credlens.dashboard.demo_package import DemoPackageError, validate_demo_package

# Row-count ceiling for any table handed to a UI component (Phase 7
# section 15: "limitacao de linhas em tabelas") - segmented/cohort tables
# at smoke/sample scale never approach this, but it is a hard backstop,
# not a soft suggestion.
MAX_TABLE_ROWS = 10_000

_MART_TABLE_NAMES: tuple[str, ...] = (
    "funnel_monthly",
    "portfolio_monthly",
    "delinquency_monthly",
    "vintage_cohorts",
    "roll_rates",
    "cure_and_redefault",
    "collections_performance",
    "writeoff_recovery",
    "scenario_comparison",
    "macro_stress_pre_post",
    "funnel_by_channel_and_scenario",
    "portfolio_by_region_and_channel",
    "policy_version_comparison",
    "credit_risk_segment_summary",
)

_DEMO_TO_MART_NAME = {"cure_redefault_summary": "cure_and_redefault"}


class DataAccessError(Exception):
    """Raised when the dashboard cannot safely access build/demo data."""


@dataclass(frozen=True)
class DashboardData:
    mode: str
    fingerprint: str
    build_id: str
    suite_id: str | None
    tables: dict[str, pd.DataFrame]
    composition: dict[str, dict[str, Any]]
    insights: list[dict[str, Any]]


def _cap_rows(df: pd.DataFrame) -> pd.DataFrame:
    return df.head(MAX_TABLE_ROWS) if len(df) > MAX_TABLE_ROWS else df


@st.cache_resource(show_spinner=False)
def _validated_build_manifest(build_id: str) -> Any:
    """Cached as a RESOURCE (Phase 7 section 15's "cache de recursos") -
    re-validates the build (dbt tests, raw-source integrity) once per
    build_id, not on every page render."""
    return validate_build_for_analysis(build_id)


@st.cache_data(show_spinner="Querying validated warehouse...")
def _load_warehouse_tables(
    build_id: str, fingerprint: str, db_path: str, suite_id: str
) -> dict[str, pd.DataFrame]:
    """`fingerprint` is part of the cache key purely for invalidation -
    if the same build_id ever gets rebuilt with a different fingerprint,
    this cache entry is naturally a miss, never stale data."""
    tables: dict[str, pd.DataFrame] = {}
    with analysis_metrics.connect(Path(db_path)) as conn:
        for name in _MART_TABLE_NAMES:
            fn = getattr(analysis_metrics, name)
            tables[name] = _cap_rows(fn(conn, suite_id))
    return tables


@st.cache_data(show_spinner="Querying validated warehouse...")
def _load_warehouse_composition(
    build_id: str, fingerprint: str, db_path: str, suite_id: str
) -> dict[str, dict[str, Any]]:
    composition: dict[str, dict[str, Any]] = {}
    with analysis_metrics.connect(Path(db_path)) as conn:
        for scenario_name in ("policy_expansion", "policy_tightening"):
            try:
                composition[scenario_name] = composition_vs_performance(
                    conn, suite_id, scenario_name
                ).to_dict()
            except ValueError:
                continue
    return composition


@st.cache_data(show_spinner=False)
def _load_demo_tables(demo_dir: str, fingerprint: str) -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}
    demo_path = Path(demo_dir)
    manifest = validate_demo_package(demo_path)
    for name in manifest.tables:
        canonical_name = _DEMO_TO_MART_NAME.get(name, name)
        tables[canonical_name] = _cap_rows(pd.read_parquet(demo_path / f"{name}.parquet"))
    return tables


@st.cache_data(show_spinner=False)
def _load_insights(path_str: str) -> list[dict[str, Any]]:
    import yaml

    path = Path(path_str)
    if not path.is_file():
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    result: list[dict[str, Any]] = payload.get("insights", [])
    return result


def load_dashboard_data(config: DashboardConfig) -> DashboardData:
    """The single entry point every page uses - never opens a
    connection or reads a file directly itself."""
    if config.mode == "warehouse":
        assert config.build_id is not None
        try:
            build = _validated_build_manifest(config.build_id)
        except AnalysisValidationError as exc:
            raise DataAccessError(str(exc)) from exc
        if build.suite_id is None:
            raise DataAccessError(
                f"Build '{config.build_id}' has no suite_id - the dashboard needs a suite "
                "(baseline + scenarios) to compare, not a single run."
            )
        tables = _load_warehouse_tables(
            build.build_id, build.analytical_fingerprint, str(build.db_path), build.suite_id
        )
        composition = _load_warehouse_composition(
            build.build_id, build.analytical_fingerprint, str(build.db_path), build.suite_id
        )
        insights_path = Path("reports/portfolio_analysis/insights.yml")
        insights = _load_insights(str(insights_path))
        return DashboardData(
            mode="warehouse",
            fingerprint=build.analytical_fingerprint,
            build_id=build.build_id,
            suite_id=build.suite_id,
            tables=tables,
            composition=composition,
            insights=insights,
        )

    # demo mode
    try:
        manifest = validate_demo_package(config.demo_data_dir)
    except DemoPackageError as exc:
        raise DataAccessError(str(exc)) from exc
    tables = _load_demo_tables(str(config.demo_data_dir), manifest.warehouse_fingerprint)
    insights_path = config.demo_data_dir / "insights.yml"
    insights = _load_insights(str(insights_path)) if manifest.insights_included else []
    return DashboardData(
        mode="demo",
        fingerprint=manifest.warehouse_fingerprint,
        build_id=manifest.source_build_id,
        suite_id=None,
        tables=tables,
        composition={},
        insights=insights,
    )


@st.cache_data(show_spinner=False)
def load_robustness_report(
    path_str: str = "reports/synthetic_validation/multiseed_robustness.json",
) -> dict[str, Any]:
    """Phase 7 gate A's multi-seed sweep result - a fixed, shared,
    scenario-agnostic artifact (not tied to any one build/suite), read
    the same way regardless of dashboard mode."""
    path = Path(path_str)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def list_available_builds(warehouse_root: Path = Path("data/warehouse")) -> list[str]:
    """An explicit allowlist of build ids that actually exist on disk -
    the dashboard's build-selection UI must only ever offer entries from
    this list, never take a free-text path (Phase 7 section 16)."""
    if not warehouse_root.is_dir():
        return []
    build_ids = []
    for entry in sorted(warehouse_root.iterdir()):
        if entry.is_dir() and (entry / "build_manifest.json").is_file():
            build_ids.append(entry.name)
    return build_ids


def read_build_summary(
    build_id: str, warehouse_root: Path = Path("data/warehouse")
) -> dict[str, Any]:
    manifest_path = warehouse_root / build_id / "build_manifest.json"
    if not manifest_path.is_file():
        raise DataAccessError(f"No build manifest found for '{build_id}'.")
    return json.loads(manifest_path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
