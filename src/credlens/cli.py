"""CredLens command-line interface.

Foundation phase: verifies the installation and the project scaffolding.
Phase 2 adds data acquisition/provenance/audit commands (`credlens data
...`). Neither phase touches models, dashboards, or business KPIs - see
docs/roadmap.md.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import platform
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from credlens import __version__
from credlens.config import Config, ConfigError, load_config
from credlens.contracts.registry import RegistryError as ContractsRegistryError
from credlens.contracts.registry import get_contract, load_all_contracts
from credlens.contracts.reporting import format_report
from credlens.contracts.validators import ValidationRunError
from credlens.contracts.validators import validate as validate_contract
from credlens.data.audit import audit_dataframe
from credlens.data.bcb_client import BcbClientError, fetch_series
from credlens.data.checksums import compute_sha256
from credlens.data.downloader import (
    DownloadError,
    download_file,
    extract_zip_safely,
    write_bytes_atomically,
)
from credlens.data.manifest import ManifestError, read_manifest, verify_manifest, write_manifest
from credlens.data.models import AcquisitionMethod, DownloadResult, ManifestEntry, SourceRecord
from credlens.data.registry import (
    RegistryError,
    get_source,
    load_registry,
    validate_status_coherence,
)
from credlens.data.schema import DatasetSchema, SchemaError, load_schema
from credlens.logging_config import configure_logging, get_logger
from credlens.synthetic import (
    BlueprintError,
    ParameterStatus,
    load_all_blueprints,
    load_blueprint,
)

logger = get_logger("cli")

_REQUIRED_DIRECTORIES = ("config", "docs", "src", "tests")
_MIN_PYTHON = (3, 11)

_RAW_SUBDIR_BY_SOURCE = {
    "uci-default-credit": "uci_default_credit",
    "south-german-credit": "south_german_credit",
    "home-credit": "home_credit",
    "bcb-sgs-20570": "bcb_sgs",
    "bcb-sgs-21112": "bcb_sgs",
}
_DOCUMENTED_NO_MISSING_VALUES = {"uci-default-credit", "south-german-credit"}
_KNOWN_ID_COLUMNS: dict[str, tuple[str, ...]] = {
    "uci-default-credit": ("ID",),
    # "data" is BCB SGS's own documented date/time-index field for a
    # single-series monthly export - unique per row by definition, not an
    # accidental artifact.
    "bcb-sgs-20570": ("data",),
    "bcb-sgs-21112": ("data",),
}

REGISTRY_PATH = Path("data/metadata/source_registry.yaml")
MANIFEST_PATH = Path("data/metadata/file_manifest.csv")
SCHEMAS_DIR = Path("data/metadata/schemas")
AUDIT_REPORTS_DIR = Path("reports/data_audit")
AUDIT_METRICS_PATH = AUDIT_REPORTS_DIR / "quality_metrics.json"

CONTRACTS_RAW_DIR = Path("contracts/raw")
CONTRACTS_OPERATIONAL_DIR = Path("contracts/operational")
SYNTHETIC_SCENARIOS_DIR = Path("config/synthetic/scenarios")
ANALYSIS_OUTPUT_DIR = Path("reports/portfolio_analysis")


@dataclass(frozen=True)
class DoctorCheck:
    """A single foundation health check reported by `credlens doctor`."""

    name: str
    status: str  # "PASS" | "FAIL" | "INFO"
    detail: str


# --- Argument parsing -------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="credlens",
        description=(
            "CredLens - Credit Risk & Portfolio Analytics. Foundation and data-acquisition CLI."
        ),
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show the CredLens package version and exit.",
    )

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("version", help="Print the CredLens package version.")
    subparsers.add_parser(
        "doctor",
        help="Check that the foundation (Python, package, config, directories) is healthy.",
    )

    data_parser = subparsers.add_parser(
        "data", help="Data acquisition, provenance, and technical audit commands (Phase 2)."
    )
    data_subparsers = data_parser.add_subparsers(dest="data_command")

    data_subparsers.add_parser("sources", help="List registered data sources. Works offline.")

    fetch_parser = data_subparsers.add_parser(
        "fetch", help="Acquire one registered data source (or all BCB SGS series)."
    )
    fetch_parser.add_argument(
        "--source",
        required=True,
        help="Source id from the registry, or 'bcb-sgs' to fetch every BCB SGS series.",
    )
    fetch_parser.add_argument(
        "--force", action="store_true", help="Overwrite an already-acquired raw file."
    )
    fetch_parser.add_argument(
        "--start", default=None, help="BCB SGS start date DD/MM/AAAA (bcb-sgs sources only)."
    )
    fetch_parser.add_argument(
        "--end",
        default=None,
        help="BCB SGS end date DD/MM/AAAA (bcb-sgs sources only; defaults to today).",
    )

    verify_parser = data_subparsers.add_parser(
        "verify", help="Recompute checksums for acquired files against the manifest."
    )
    verify_parser.add_argument("--source", default=None, help="Limit to one source id.")

    audit_parser = data_subparsers.add_parser(
        "audit",
        help="Run the reproducible structural audit on already-acquired raw files. "
        "Never downloads anything.",
    )
    audit_parser.add_argument("--source", default=None, help="Limit to one source id.")

    contracts_parser = subparsers.add_parser(
        "contracts", help="Data contract listing and validation commands (Phase 3)."
    )
    contracts_subparsers = contracts_parser.add_subparsers(dest="contracts_command")

    contracts_subparsers.add_parser(
        "list", help="List every known contract (raw + operational). Works offline."
    )

    show_parser = contracts_subparsers.add_parser("show", help="Show full detail for one contract.")
    show_parser.add_argument("name", help="Contract name, e.g. 'applications'.")

    contracts_validate_parser = contracts_subparsers.add_parser(
        "validate", help="Validate a file or scenario directory against one contract."
    )
    contracts_validate_parser.add_argument("--contract", required=True, help="Contract name.")
    contracts_validate_parser.add_argument(
        "--path",
        required=True,
        help="Path to a data file, or a scenario directory containing multiple "
        "<contract_name>.<format> files (see contracts/README.md).",
    )
    contracts_validate_parser.add_argument(
        "--mode",
        required=True,
        choices=["audit", "strict"],
        help="'audit' never fails the command (diagnostic); 'strict' fails on any error finding.",
    )

    synthetic_parser = subparsers.add_parser(
        "synthetic",
        help="Synthetic-generation commands (Phase 4A: baseline scenario only).",
    )
    synthetic_subparsers = synthetic_parser.add_subparsers(dest="synthetic_command")
    synthetic_subparsers.add_parser(
        "plan", help="Summarize synthetic-generation readiness. Works offline."
    )
    synthetic_subparsers.add_parser(
        "scenarios", help="List scenario blueprints and their status. Works offline."
    )
    synthetic_subparsers.add_parser(
        "validate-blueprints", help="Structurally validate every scenario blueprint. Works offline."
    )

    generate_parser = synthetic_subparsers.add_parser(
        "generate", help="Run the deterministic generator (baseline scenario only in Phase 4A)."
    )
    generate_parser.add_argument(
        "--scenario", required=True, help="Scenario name, e.g. 'baseline'."
    )
    generate_parser.add_argument(
        "--scale",
        required=True,
        choices=["smoke", "sample", "portfolio"],
        help="Generation scale preset.",
    )
    generate_parser.add_argument(
        "--seed", required=True, type=int, help="Random seed (required for determinism)."
    )
    generate_parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing run with the same id."
    )

    validate_run_parser = synthetic_subparsers.add_parser(
        "validate", help="Re-validate an already-generated run's operational tables in strict mode."
    )
    validate_run_parser.add_argument(
        "--run-id", required=True, help="generation_run_id to validate."
    )

    inspect_parser = synthetic_subparsers.add_parser(
        "inspect", help="Summarize an already-generated run: tables, row counts, key statistics."
    )
    inspect_parser.add_argument("--run-id", required=True, help="generation_run_id to inspect.")

    manifest_parser = synthetic_subparsers.add_parser(
        "manifest", help="Print the manifest.json of an already-generated run."
    )
    manifest_parser.add_argument(
        "--run-id", required=True, help="generation_run_id whose manifest to print."
    )

    suite_parser = synthetic_subparsers.add_parser(
        "generate-suite",
        help="Generate a baseline run plus every CRN scenario run for the same seed (Phase 4B).",
    )
    suite_parser.add_argument(
        "--scale", required=True, choices=["smoke", "sample", "portfolio"], help="Scale preset."
    )
    suite_parser.add_argument("--seed", required=True, type=int, help="Random seed.")
    suite_parser.add_argument(
        "--force", action="store_true", help="Overwrite existing runs with the same id."
    )

    compare_parser = synthetic_subparsers.add_parser(
        "compare", help="Compare two already-generated runs' aggregate technical metrics."
    )
    compare_parser.add_argument("--baseline", required=True, help="Baseline generation_run_id.")
    compare_parser.add_argument("--candidate", required=True, help="Candidate generation_run_id.")

    validate_suite_parser = synthetic_subparsers.add_parser(
        "validate-suite", help="Re-validate every run in a suite in strict mode."
    )
    validate_suite_parser.add_argument("--suite-id", required=True, help="suite_id to validate.")

    monte_carlo_parser = synthetic_subparsers.add_parser(
        "monte-carlo", help="Compare baseline vs. a scenario across multiple seeds (Phase 4B)."
    )
    monte_carlo_parser.add_argument("--scenario", required=True, help="Scenario name.")
    monte_carlo_parser.add_argument(
        "--scale", required=True, choices=["smoke", "sample", "portfolio"], help="Scale preset."
    )
    monte_carlo_parser.add_argument(
        "--seeds", required=True, type=int, help="Number of seeds to run."
    )
    monte_carlo_parser.add_argument(
        "--start-seed",
        type=int,
        default=2026,
        help="First seed in the sweep (default: 2026); subsequent seeds increment by 1. "
        "Override this in tests/CI so a sweep never reuses the same seeds an official "
        "demonstration run/suite occupies (Phase 6 gate B).",
    )

    profile_parser = synthetic_subparsers.add_parser(
        "profile", help="Run the generator once cleanly (timing/memory) and once under cProfile."
    )
    profile_parser.add_argument(
        "--scale", required=True, choices=["smoke", "sample", "portfolio"], help="Scale preset."
    )
    profile_parser.add_argument("--seed", required=True, type=int, help="Random seed.")
    profile_parser.add_argument(
        "--scenario", default="baseline", help="Scenario name (default: baseline)."
    )

    warehouse_parser = subparsers.add_parser(
        "warehouse",
        help="DuckDB + dbt analytical warehouse commands (Phase 5).",
    )
    warehouse_subparsers = warehouse_parser.add_subparsers(dest="warehouse_command")

    def _add_selection_args(p: argparse.ArgumentParser) -> None:
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument("--run-id", default=None, help="A single generation_run_id to load.")
        group.add_argument(
            "--suite-id", default=None, help="A suite_id (baseline + every CRN scenario) to load."
        )
        p.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")

    prepare_parser = warehouse_subparsers.add_parser(
        "prepare",
        help="Validate a run/suite is safe to load (manifest, hashes, quarantine, "
        "contract version) without invoking dbt.",
    )
    _add_selection_args(prepare_parser)

    build_parser = warehouse_subparsers.add_parser(
        "build", help="Resolve sources and run a full `dbt build` (raw..marts + all tests)."
    )
    _add_selection_args(build_parser)
    build_parser.add_argument(
        "--build-id", default=None, help="Explicit build id (default: auto-generated)."
    )
    build_parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing build with the same build id."
    )

    test_parser = warehouse_subparsers.add_parser(
        "test", help="Re-run dbt tests (no rebuild) against an already-built warehouse."
    )
    test_parser.add_argument("--build-id", required=True, help="build_id from a prior build.")
    test_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output."
    )

    status_parser = warehouse_subparsers.add_parser(
        "status", help="Show a prior build's manifest (versions, counts, tests, fingerprint)."
    )
    status_parser.add_argument("--build-id", required=True, help="build_id from a prior build.")
    status_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output."
    )

    query_parser = warehouse_subparsers.add_parser(
        "query", help="Run one named demo analytical query against a built warehouse."
    )
    query_parser.add_argument("--build-id", required=True, help="build_id from a prior build.")
    query_parser.add_argument("--name", required=True, help="Named query - see --help for options.")
    query_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output."
    )

    docs_parser = warehouse_subparsers.add_parser(
        "docs", help="Generate (not serve) the dbt docs static site for a build."
    )
    docs_parser.add_argument("--build-id", required=True, help="build_id from a prior build.")

    reconcile_parser = warehouse_subparsers.add_parser(
        "reconcile",
        help="Independently re-verify a sample of critical KPIs in Python, "
        "reading raw source parquet directly (never through dbt/SQL).",
    )
    reconcile_parser.add_argument("--build-id", required=True, help="build_id from a prior build.")
    reconcile_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output."
    )

    analysis_parser = subparsers.add_parser(
        "analysis",
        help="Reproducible portfolio-analysis layer: SQL-first metrics, scenario "
        "comparison, charts, and bilingual reports over a built warehouse (Phase 6).",
    )
    analysis_subparsers = analysis_parser.add_subparsers(dest="analysis_command")

    analysis_validate_parser = analysis_subparsers.add_parser(
        "validate",
        help="Check a build is safe to analyze (tests passed, sources unmutated, "
        "fingerprint present) without running the full analysis.",
    )
    analysis_validate_parser.add_argument("--build-id", required=True, help="build_id to validate.")
    analysis_validate_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output."
    )

    analysis_run_parser = analysis_subparsers.add_parser(
        "run",
        help="Run the full analysis (metrics, scenario comparison, charts, bilingual "
        "reports, provenance manifest) against a built warehouse.",
    )
    analysis_run_parser.add_argument(
        "--build-id", required=True, help="build_id from a prior build."
    )
    analysis_run_parser.add_argument(
        "--output-dir",
        default=None,
        help=f"Output directory (default: {ANALYSIS_OUTPUT_DIR}).",
    )
    analysis_run_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing analysis at the same output dir.",
    )
    analysis_run_parser.add_argument(
        "--no-benchmark", action="store_true", help="Skip the public-dataset benchmark appendix."
    )
    analysis_run_parser.add_argument(
        "--multiseed", action="store_true", help="Also run a real multi-seed robustness sweep."
    )
    analysis_run_parser.add_argument(
        "--multiseed-scenario", default="macroeconomic_stress", help="Scenario for --multiseed."
    )
    analysis_run_parser.add_argument(
        "--multiseed-scale",
        default="smoke",
        choices=["smoke", "sample", "portfolio"],
        help="Scale for --multiseed (default: smoke - never portfolio, Phase 6 section 13).",
    )
    analysis_run_parser.add_argument(
        "--multiseed-seeds", type=int, default=5, help="Number of seeds for --multiseed."
    )
    analysis_run_parser.add_argument(
        "--insights",
        action="store_true",
        help="Also generate the verifiable insights registry (Phase 7 gate D) at "
        "<output-dir>/insights.yml, hashed into the reproducibility fingerprint (gate E).",
    )
    analysis_run_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output."
    )

    analysis_scenarios_parser = analysis_subparsers.add_parser(
        "scenarios",
        help="Paired scenario comparison (baseline vs. each scenario) and "
        "composition-vs-performance for policy_expansion/policy_tightening, without "
        "writing the full report tree.",
    )
    analysis_scenarios_parser.add_argument(
        "--build-id", required=True, help="build_id from a prior build."
    )
    analysis_scenarios_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output."
    )

    analysis_benchmark_parser = analysis_subparsers.add_parser(
        "benchmark",
        help="Profile the already-acquired public benchmark sources (UCI, South German "
        "Credit, BCB SGS), kept separate from any synthetic build.",
    )
    analysis_benchmark_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output."
    )

    analysis_status_parser = analysis_subparsers.add_parser(
        "status", help="Show a prior analysis run's provenance manifest."
    )
    analysis_status_parser.add_argument(
        "--output-dir",
        default=None,
        help=f"Analysis output directory (default: {ANALYSIS_OUTPUT_DIR}).",
    )
    analysis_status_parser.add_argument(
        "--analysis-id",
        default=None,
        help="If given, verifies the manifest at --output-dir belongs to this analysis_id.",
    )
    analysis_status_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output."
    )

    analysis_reproduce_parser = analysis_subparsers.add_parser(
        "reproduce",
        help="Re-run a prior analysis (same build_id) into a separate directory and "
        "verify its table/figure content hashes match the original exactly.",
    )
    analysis_reproduce_parser.add_argument(
        "--output-dir",
        default=None,
        help=f"Original analysis output directory to reproduce (default: {ANALYSIS_OUTPUT_DIR}).",
    )
    analysis_reproduce_parser.add_argument(
        "--analysis-id",
        default=None,
        help="If given, verifies the manifest at --output-dir belongs to this analysis_id.",
    )
    analysis_reproduce_parser.add_argument(
        "--reproduce-dir",
        default=None,
        help="Where to write the reproduction run (default: <output-dir>_reproduce).",
    )
    analysis_reproduce_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output."
    )

    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Streamlit decision-intelligence dashboard: validate a data source, export a "
        "small demo package, and run the app (Phase 7).",
    )
    dashboard_subparsers = dashboard_parser.add_subparsers(dest="dashboard_command")

    dashboard_validate_parser = dashboard_subparsers.add_parser(
        "validate",
        help="Check a build or the demo package is safe to display, without launching Streamlit.",
    )
    dashboard_validate_group = dashboard_validate_parser.add_mutually_exclusive_group(required=True)
    dashboard_validate_group.add_argument("--build-id", default=None, help="build_id to validate.")
    dashboard_validate_group.add_argument(
        "--demo", action="store_true", help="Validate the demo package instead of a build."
    )
    dashboard_validate_parser.add_argument(
        "--demo-data-dir",
        default=None,
        help="Demo package directory (default: dashboard/demo_data).",
    )
    dashboard_validate_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output."
    )

    dashboard_export_demo_parser = dashboard_subparsers.add_parser(
        "export-demo",
        help="Build the small, versionable demo aggregate package from a validated "
        "`credlens analysis run` output directory.",
    )
    dashboard_export_demo_parser.add_argument(
        "--build-id", required=True, help="build_id whose analysis output to export from."
    )
    dashboard_export_demo_parser.add_argument(
        "--analysis-output-dir",
        default=None,
        help=f"Analysis output directory to export from (default: {ANALYSIS_OUTPUT_DIR}).",
    )
    dashboard_export_demo_parser.add_argument(
        "--output-dir",
        default=None,
        help="Where to write the demo package (default: dashboard/demo_data).",
    )
    dashboard_export_demo_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing demo package at the same output dir.",
    )
    dashboard_export_demo_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output."
    )

    dashboard_run_parser = dashboard_subparsers.add_parser(
        "run", help="Launch the Streamlit dashboard against a validated build or the demo package."
    )
    dashboard_run_group = dashboard_run_parser.add_mutually_exclusive_group(required=True)
    dashboard_run_group.add_argument("--build-id", default=None, help="build_id to display.")
    dashboard_run_group.add_argument(
        "--demo", action="store_true", help="Run against the demo aggregate package instead."
    )
    dashboard_run_parser.add_argument(
        "--demo-data-dir",
        default=None,
        help="Demo package directory (default: dashboard/demo_data).",
    )
    dashboard_run_parser.add_argument(
        "--port", type=int, default=8501, help="TCP port for the Streamlit server (default: 8501)."
    )
    dashboard_run_parser.add_argument(
        "--no-browser", action="store_true", help="Do not automatically open a browser tab."
    )

    dashboard_status_parser = dashboard_subparsers.add_parser(
        "status", help="Show the demo package's manifest and the builds available to run against."
    )
    dashboard_status_parser.add_argument(
        "--demo-data-dir",
        default=None,
        help="Demo package directory (default: dashboard/demo_data).",
    )
    dashboard_status_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output."
    )

    demo_parser = subparsers.add_parser(
        "demo",
        help="Deterministic demo-data factory (Fase 11C) - prepares the dashboard's demo "
        "Parquet bundle and/or the monitoring reference+batches from scratch, so neither "
        "depends on a locally-generated file already sitting on disk.",
    )
    demo_subparsers = demo_parser.add_subparsers(dest="demo_command")

    demo_prepare_parser = demo_subparsers.add_parser(
        "prepare",
        help="Generate one or both demo-data components deterministically.",
    )
    demo_prepare_parser.add_argument(
        "--component",
        choices=["dashboard", "monitoring", "all"],
        required=True,
        help="Which component to prepare.",
    )
    demo_prepare_parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed for the dashboard component's synthetic suite (default: 42). Ignored for "
        "'monitoring', which is deterministic from the already-registered, already-frozen "
        "official model instead.",
    )
    demo_prepare_parser.add_argument(
        "--output",
        default=None,
        help="Where to write the dashboard component's bundle (default: dashboard/demo_data). "
        "Not applicable to 'monitoring', which always (re)writes the existing, already-"
        "gitignored reports/monitoring/ locations its own evaluation commands read from.",
    )
    demo_prepare_parser.add_argument(
        "--model-id",
        default=None,
        help="Model id for the monitoring component (default: the official "
        "MODEL_behavioral_default_v1).",
    )
    demo_prepare_parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if a complete, matching bundle already exists.",
    )
    demo_prepare_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output."
    )

    model_parser = subparsers.add_parser(
        "model",
        help="Interpretable behavioral early-warning default model on the UCI public "
        "benchmark (Phase 8) - never an origination score, never a real lending decision.",
    )
    model_subparsers = model_parser.add_subparsers(dest="model_command")

    model_subparsers.add_parser(
        "data-audit", help="Audit the acquired UCI benchmark (hash, prevalence, domains)."
    ).add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")

    model_subparsers.add_parser(
        "validate-features",
        help="Engineer features from the real source and re-run every static leakage control.",
    ).add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")

    model_create_split_parser = model_subparsers.add_parser(
        "create-split", help="Create and lock the stratified 60/20/20 split for an experiment."
    )
    model_create_split_parser.add_argument("--experiment-id", required=True)
    model_create_split_parser.add_argument("--seed", type=int, default=42)
    model_create_split_parser.add_argument("--json", action="store_true")

    model_train_parser = model_subparsers.add_parser(
        "train",
        help="Fit Dummy/simple-rule baselines and tune the logistic regression + "
        "HistGradientBoosting challenger, train-only.",
    )
    model_train_parser.add_argument("--experiment-id", required=True)
    model_train_parser.add_argument("--seed", type=int, default=42)
    model_train_parser.add_argument("--json", action="store_true")

    model_evaluate_parser = model_subparsers.add_parser(
        "evaluate", help="Compute the full metrics suite, operating points, and uncertainty."
    )
    model_evaluate_parser.add_argument("--experiment-id", required=True)
    model_evaluate_parser.add_argument("--json", action="store_true")

    model_compare_parser = model_subparsers.add_parser(
        "compare", help="Champion/challenger comparison table for an evaluated experiment."
    )
    model_compare_parser.add_argument("--experiment-id", required=True)
    model_compare_parser.add_argument("--json", action="store_true")

    model_explain_parser = model_subparsers.add_parser(
        "explain",
        help="Global/feature-response/local interpretability for the main interpretable model.",
    )
    model_explain_parser.add_argument("--experiment-id", required=True)
    model_explain_parser.add_argument("--json", action="store_true")

    model_audit_groups_parser = model_subparsers.add_parser(
        "audit-groups",
        help="Post-hoc subgroup diagnostics - not a fairness certification or compliance check.",
    )
    model_audit_groups_parser.add_argument("--experiment-id", required=True)
    model_audit_groups_parser.add_argument("--json", action="store_true")

    model_stress_test_parser = model_subparsers.add_parser(
        "stress-test", help="Perturbation robustness suite - technical, not a crisis forecast."
    )
    model_stress_test_parser.add_argument("--experiment-id", required=True)
    model_stress_test_parser.add_argument("--json", action="store_true")

    model_register_parser = model_subparsers.add_parser(
        "register",
        help="Evaluate promotion gates and, if eligible, register a 'candidate' model "
        "(never 'production', never auto-promoted).",
    )
    model_register_parser.add_argument("--experiment-id", required=True)
    model_register_parser.add_argument("--model-id", required=True)
    model_register_parser.add_argument("--json", action="store_true")

    model_validate_parser = model_subparsers.add_parser(
        "validate", help="Hash-verify and schema-validate a registered model candidate."
    )
    model_validate_parser.add_argument("--model-id", required=True)
    model_validate_parser.add_argument("--json", action="store_true")

    model_predict_batch_parser = model_subparsers.add_parser(
        "predict-batch",
        help="Batch-score a UCI-schema-shaped CSV - never an approve/reject decision.",
    )
    model_predict_batch_parser.add_argument("--model-id", required=True)
    model_predict_batch_parser.add_argument(
        "--input", required=True, help="CSV shaped like the raw UCI benchmark (ID, X1..X23)."
    )
    model_predict_batch_parser.add_argument(
        "--output", default=None, help="Where to write the scored CSV (default: stdout summary)."
    )
    model_predict_batch_parser.add_argument("--json", action="store_true")

    model_report_parser = model_subparsers.add_parser(
        "report", help="Generate bilingual model card + technical report + figures + manifest."
    )
    model_report_parser.add_argument("--experiment-id", required=True)
    model_report_parser.add_argument("--model-id", default=None)
    model_report_parser.add_argument(
        "--no-figures", action="store_true", help="Skip figure generation (matplotlib not needed)."
    )
    model_report_parser.add_argument("--json", action="store_true")

    # --- Phase 9: independent validation + challenger subcommands ----------

    model_validate_independent_parser = model_subparsers.add_parser(
        "validate-independent",
        help="Independent re-validation (Phase 9) - recomputes evidence from frozen artifacts, "
        "never copies the Phase 8 report.",
    )
    model_validate_independent_parser.add_argument("--model-id", required=True)
    model_validate_independent_parser.add_argument(
        "--ci",
        action="store_true",
        help="Use the reduced CI permutation count instead of the full 100.",
    )
    model_validate_independent_parser.add_argument("--json", action="store_true")

    model_audit_collinearity_parser = model_subparsers.add_parser(
        "audit-collinearity",
        help="Multicollinearity/coefficient-stability audit (Phase 9 section 7).",
    )
    model_audit_collinearity_parser.add_argument("--model-id", required=True)
    model_audit_collinearity_parser.add_argument("--json", action="store_true")

    model_audit_negative_controls_parser = model_subparsers.add_parser(
        "audit-negative-controls",
        help="Permutation-based negative control (Phase 9 section 6) - replaces the Phase 8 "
        "fixed-band shuffled-target check.",
    )
    model_audit_negative_controls_parser.add_argument("--experiment-id", required=True)
    model_audit_negative_controls_parser.add_argument(
        "--ci",
        action="store_true",
        help="Use the reduced CI permutation count instead of the full 100.",
    )
    model_audit_negative_controls_parser.add_argument("--json", action="store_true")

    model_compare_candidates_parser = model_subparsers.add_parser(
        "compare-candidates",
        help="Candidate/challenger Pareto trade-off comparison (Phase 9 section 8.1).",
    )
    model_compare_candidates_parser.add_argument("--experiment-id", default=None)
    model_compare_candidates_parser.add_argument("--json", action="store_true")

    model_register_challenger_parser = model_subparsers.add_parser(
        "register-challenger",
        help="Registers the HistGradientBoosting model as a 'challenger' (Phase 9 section 8) - "
        "never 'candidate', never 'production'.",
    )
    model_register_challenger_parser.add_argument("--experiment-id", required=True)
    model_register_challenger_parser.add_argument("--model-id", default=None)
    model_register_challenger_parser.add_argument("--json", action="store_true")

    # --- Phase 10 gate D: remediation subcommands ---------------------------

    model_remediate_parser = model_subparsers.add_parser(
        "remediate",
        help="Post-validation remediation (Phase 10 gate D) - builds a NEW, separately "
        "registered logistic regression on a documented reduced feature set "
        "(config/model_validation/remediation_policy.yml), never overwriting the original "
        "model/experiment.",
    )
    model_remediate_parser.add_argument("--model-id", required=True, help="Original model_id (v1).")
    model_remediate_parser.add_argument(
        "--new-experiment-id",
        default="EXP_behavioral_default_v2_reduced",
        help="Experiment id for the remediated model (default: EXP_behavioral_default_v2_reduced).",
    )
    model_remediate_parser.add_argument(
        "--new-model-id",
        default="MODEL_behavioral_default_v2_reduced",
        help="Model id to register the remediated model under IF the decision is "
        "remediation_candidate (default: MODEL_behavioral_default_v2_reduced).",
    )
    model_remediate_parser.add_argument("--json", action="store_true")

    model_compare_remediation_parser = model_subparsers.add_parser(
        "compare-remediation",
        help="Prints the 5-model gate D comparison (original/VIF-reduced/stability-reduced/"
        "final remediated/HistGBM challenger) - read-only, requires 'model remediate' to have "
        "already run once.",
    )
    model_compare_remediation_parser.add_argument(
        "--new-experiment-id", default="EXP_behavioral_default_v2_reduced"
    )
    model_compare_remediation_parser.add_argument("--json", action="store_true")

    # --- Phase 9: monitor command group --------------------------------------

    monitor_parser = subparsers.add_parser(
        "monitor",
        help="Monitoring simulation on a historical public benchmark (Phase 9) - never a real "
        "production monitoring system.",
    )
    monitor_subparsers = monitor_parser.add_subparsers(dest="monitor_command")

    monitor_create_reference_parser = monitor_subparsers.add_parser(
        "create-reference", help="Builds the monitoring reference from train+validation only."
    )
    monitor_create_reference_parser.add_argument("--model-id", required=True)
    monitor_create_reference_parser.add_argument("--json", action="store_true")

    monitor_calibrate_reference_parser = monitor_subparsers.add_parser(
        "calibrate-reference",
        help="Phase 10 gate F - adds a family-wise PSI threshold (calibrated on the max PSI "
        "across all features) to an already-built reference, fixing the ~60% family-wise "
        "false-alert rate the per-feature-only calibration produces.",
    )
    monitor_calibrate_reference_parser.add_argument("--reference-id", required=True)
    monitor_calibrate_reference_parser.add_argument("--json", action="store_true")

    monitor_evaluate_false_alerts_parser = monitor_subparsers.add_parser(
        "evaluate-false-alerts",
        help="Phase 10 gate F - measures real false-alert rates over >=100 unperturbed "
        "baseline-like batches drawn from the locked test set.",
    )
    monitor_evaluate_false_alerts_parser.add_argument("--reference-id", required=True)
    monitor_evaluate_false_alerts_parser.add_argument("--n-batches", type=int, default=100)
    monitor_evaluate_false_alerts_parser.add_argument("--batch-size", type=int, default=500)
    monitor_evaluate_false_alerts_parser.add_argument("--json", action="store_true")

    monitor_evaluate_detection_parser = monitor_subparsers.add_parser(
        "evaluate-detection",
        help="Phase 10 gate F/G - detection matrix across the 12 perturbation scenarios "
        "(expected vs. detected signal/alert/incident, severity, blocking).",
    )
    monitor_evaluate_detection_parser.add_argument("--reference-id", required=True)
    monitor_evaluate_detection_parser.add_argument("--json", action="store_true")

    monitor_simulate_batches_parser = monitor_subparsers.add_parser(
        "simulate-batches", help="Builds the 12 simulated batches from the locked test set."
    )
    monitor_simulate_batches_parser.add_argument("--reference-id", required=True)
    monitor_simulate_batches_parser.add_argument("--json", action="store_true")

    monitor_run_parser = monitor_subparsers.add_parser(
        "run",
        help="Scores every batch and computes data quality/drift/performance/subgroup/alerts.",
    )
    monitor_run_parser.add_argument("--reference-id", required=True)
    monitor_run_parser.add_argument("--batch-set", required=True)
    monitor_run_parser.add_argument("--json", action="store_true")

    monitor_status_parser = monitor_subparsers.add_parser(
        "status", help="Summarizes a monitoring run."
    )
    monitor_status_parser.add_argument("--run-id", required=True)
    monitor_status_parser.add_argument("--json", action="store_true")

    monitor_alerts_parser = monitor_subparsers.add_parser(
        "alerts", help="Lists alerts for a monitoring run."
    )
    monitor_alerts_parser.add_argument("--run-id", required=True)
    monitor_alerts_parser.add_argument("--json", action="store_true")

    monitor_report_parser = monitor_subparsers.add_parser(
        "report", help="Writes the bilingual monitoring report + manifest."
    )
    monitor_report_parser.add_argument("--run-id", required=True)
    monitor_report_parser.add_argument("--json", action="store_true")

    monitor_validate_parser = monitor_subparsers.add_parser(
        "validate", help="Structural integrity check of a monitoring run's artifacts."
    )
    monitor_validate_parser.add_argument("--run-id", required=True)
    monitor_validate_parser.add_argument("--json", action="store_true")

    # --- Phase 10: release command group ------------------------------------

    release_parser = subparsers.add_parser(
        "release",
        help="Release-engineering checks (Phase 10) - integrity validation, license "
        "inventory, SBOM, deterministic release manifest, readiness decision. All local "
        "only - no network access, no external service.",
    )
    release_subparsers = release_parser.add_subparsers(dest="release_command")

    release_validate_parser = release_subparsers.add_parser(
        "validate",
        help="Runs the release integrity checklist (version, lockfile, license, "
        "secrets, large files, bilingual reports, model artifacts, CI masking patterns).",
    )
    release_validate_parser.add_argument("--json", action="store_true")

    release_licenses_parser = release_subparsers.add_parser(
        "licenses",
        help="Dependency license inventory from installed package metadata - engineering "
        "inventory, not legal advice.",
    )
    release_licenses_parser.add_argument("--json", action="store_true")

    release_sbom_parser = release_subparsers.add_parser(
        "sbom", help="Generates a CycloneDX-format SBOM from installed package metadata."
    )
    release_sbom_parser.add_argument("--json", action="store_true")

    release_manifest_parser = release_subparsers.add_parser(
        "manifest",
        help="Builds the deterministic release manifest and readiness decision, and writes "
        "it to reports/release/release_manifest.json.",
    )
    release_manifest_parser.add_argument(
        "--visual-qa-status",
        default="not_verified",
        choices=["not_verified", "verified_locally"],
    )
    release_manifest_parser.add_argument(
        "--docker-status",
        default="not_executed",
        choices=["not_executed", "built_and_validated", "build_failed"],
    )
    release_manifest_parser.add_argument(
        "--security-scan-status",
        default="not_executed",
        choices=["not_executed", "verified", "failed"],
    )
    release_manifest_parser.add_argument("--ci-status", default="not_run_remotely_this_session")
    release_manifest_parser.add_argument("--test-total", type=int, default=None)
    release_manifest_parser.add_argument("--json", action="store_true")

    release_status_parser = release_subparsers.add_parser(
        "status", help="Prints the last written release manifest, if any."
    )
    release_status_parser.add_argument("--json", action="store_true")

    release_errata_parser = release_subparsers.add_parser(
        "errata",
        help="Prints the append-only release errata log (Phase 10B) - corrections to a "
        "previously emitted readiness decision, never a deletion of the original.",
    )
    release_errata_parser.add_argument("--json", action="store_true")

    release_measure_coverage_parser = release_subparsers.add_parser(
        "measure-coverage",
        help="Reads a real 'coverage.json' (from 'pytest --cov-report=json:coverage.json') and "
        "writes a source-fingerprint-stamped coverage snapshot for the release-integrity "
        "coverage gate (Phase 10B).",
    )
    release_measure_coverage_parser.add_argument(
        "--coverage-json", default="coverage.json", help="Path to coverage.py's own JSON report."
    )
    release_measure_coverage_parser.add_argument("--test-count", type=int, required=True)
    release_measure_coverage_parser.add_argument(
        "--pytest-command",
        dest="pytest_command",
        required=True,
        help='The exact pytest command that produced --coverage-json (e.g. "uv run pytest '
        '--cov=credlens --cov-report=json:coverage.json --cov-fail-under=95") - recorded as '
        "evidence and checked for the required flag/full-suite shape, never re-executed.",
    )
    release_measure_coverage_parser.add_argument(
        "--pytest-exit-code",
        type=int,
        required=True,
        help="The exit code that pytest command actually returned - a nonzero value fails the "
        "gate (a failing or otherwise incomplete test run must never produce accepted evidence).",
    )
    release_measure_coverage_parser.add_argument("--json", action="store_true")

    release_checksums_parser = release_subparsers.add_parser(
        "checksums",
        help="(Re)generates reports/release/SHA256SUMS from the current content of the "
        "canonical release-asset set (Fase 12) - must be run AFTER release_manifest.json/"
        "sbom.cyclonedx.json/license_inventory.json are already up to date, since it only "
        "reads them, never regenerates them.",
    )
    release_checksums_parser.add_argument("--json", action="store_true")

    release_security_parser = release_subparsers.add_parser(
        "security",
        help="Judges real pip-audit/Trivy JSON reports (Fase 14) against this project's "
        "blocking policy (CRITICAL always blocks; HIGH blocks only when a fix is already "
        "available; a missing report or a secret found in the image always blocks) and "
        "writes reports/release/security_audit.json. Never runs the scanners itself - see "
        "docs/release_checklist.md for the exact pip-audit/Trivy invocations expected first.",
    )
    release_security_parser.add_argument(
        "--pip-audit-report",
        required=True,
        type=Path,
        help="Path to pip-audit's --format json output.",
    )
    release_security_parser.add_argument(
        "--trivy-report",
        required=True,
        type=Path,
        help="Path to trivy image's --format json output.",
    )
    release_security_parser.add_argument("--json", action="store_true")

    return parser


# --- version / doctor (Phase 1) ---------------------------------------------


def _cmd_version() -> int:
    print(f"credlens {__version__}")
    return 0


def _check_data_sources() -> DoctorCheck:
    if not REGISTRY_PATH.is_file():
        return DoctorCheck("data_sources", "INFO", "not configured (future phase)")
    try:
        records = load_registry(REGISTRY_PATH)
    except RegistryError as exc:
        return DoctorCheck("data_sources", "INFO", f"registry present but invalid: {exc}")

    counts: dict[str, int] = {}
    for record in records:
        counts[record.status.value] = counts.get(record.status.value, 0) + 1
    summary = ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
    return DoctorCheck("data_sources", "INFO", f"{len(records)} registered ({summary})")


def run_doctor_checks() -> list[DoctorCheck]:
    """Run all foundation health checks and return their results.

    Exposed as a standalone function so it can be unit tested without
    parsing the CLI's stdout.
    """
    checks: list[DoctorCheck] = []

    python_version = platform.python_version()
    python_ok = sys.version_info >= _MIN_PYTHON
    checks.append(DoctorCheck("python_version", "PASS" if python_ok else "FAIL", python_version))

    checks.append(DoctorCheck("package_version", "PASS", __version__))

    try:
        config = load_config()
        checks.append(DoctorCheck("config_file", "PASS", str(config.source_path)))
    except ConfigError as exc:
        checks.append(DoctorCheck("config_file", "FAIL", str(exc)))

    for directory in _REQUIRED_DIRECTORIES:
        exists = Path(directory).is_dir()
        status = "PASS" if exists else "FAIL"
        checks.append(DoctorCheck(f"directory:{directory}", status, directory))

    # Data acquisition status is informational: an unregistered/undownloaded
    # source is expected at this stage of the project and must not be
    # reported as a failure of the current installation.
    checks.append(_check_data_sources())

    return checks


def _cmd_doctor() -> int:
    checks = run_doctor_checks()

    print("CredLens doctor")
    print("=" * 16)
    for check in checks:
        print(f"[{check.status:>4}] {check.name:<24} {check.detail}")

    has_failure = any(check.status == "FAIL" for check in checks)
    print()
    print(f"Result: {'FAIL' if has_failure else 'OK'}")
    return 1 if has_failure else 0


# --- data sources ------------------------------------------------------------


def _read_manifest_source_ids() -> set[str]:
    if not MANIFEST_PATH.is_file():
        return set()
    try:
        return {entry.source_id for entry in read_manifest(MANIFEST_PATH)}
    except ManifestError:
        return set()


def _read_audited_source_ids() -> set[str]:
    if not AUDIT_METRICS_PATH.is_file():
        return set()
    try:
        payload = json.loads(AUDIT_METRICS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    sources = payload.get("sources") if isinstance(payload, dict) else None
    return set(sources.keys()) if isinstance(sources, dict) else set()


def _cmd_data_sources() -> int:
    try:
        records = load_registry(REGISTRY_PATH)
    except RegistryError as exc:
        print(f"Error: {exc}")
        return 1

    issues = validate_status_coherence(
        records,
        manifest_source_ids=_read_manifest_source_ids(),
        audited_source_ids=_read_audited_source_ids(),
    )

    print("CredLens data sources")
    print("=" * 22)
    print(f"{'ID':<22} {'ROLE':<20} {'STATUS':<11} {'METHOD':<10} NAME")
    for record in sorted(records, key=lambda r: r.id):
        print(
            f"{record.id:<22} {record.role.value:<20} {record.status.value:<11} "
            f"{record.acquisition_method.value:<10} {record.name}"
        )

    if issues:
        print()
        print("Coherence issues:")
        for issue in issues:
            print(f"  - {issue.source_id}: {issue.problem}")

    return 0


# --- data fetch ---------------------------------------------------------------


def _relative_to_cwd(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _format_from_suffix(path: Path) -> str:
    return path.suffix.lstrip(".").lower() or "unknown"


def _entry_from_download(record: SourceRecord, result: DownloadResult) -> ManifestEntry:
    return ManifestEntry(
        source_id=record.id,
        relative_path=_relative_to_cwd(result.path),
        filename=result.path.name,
        size_bytes=result.size_bytes,
        sha256=result.sha256,
        retrieved_at_utc=result.retrieved_at_utc,
        url=result.final_url,
        format=_format_from_suffix(result.path),
        num_rows=None,
        num_columns=None,
        verification_status="unverified",
        source_version_or_date=record.period,
        license=record.license,
        notes="",
    )


def _entry_for_extracted(
    record: SourceRecord, member_path: Path, retrieved_at: str
) -> ManifestEntry:
    return ManifestEntry(
        source_id=record.id,
        relative_path=_relative_to_cwd(member_path),
        filename=member_path.name,
        size_bytes=member_path.stat().st_size,
        sha256=compute_sha256(member_path),
        retrieved_at_utc=retrieved_at,
        url=record.acquisition_url or "",
        format=_format_from_suffix(member_path),
        num_rows=None,
        num_columns=None,
        verification_status="unverified",
        source_version_or_date=record.period,
        license=record.license,
        notes=f"Extracted from {record.filename or 'archive'}.",
    )


def _fetch_http(record: SourceRecord, config: Config, force: bool) -> list[ManifestEntry]:
    if record.acquisition_url is None or record.filename is None:
        raise DownloadError(f"{record.id}: registry entry has no acquisition_url/filename.")

    dest_dir = Path(config.data.raw_dir) / _RAW_SUBDIR_BY_SOURCE[record.id]

    result = download_file(
        record.acquisition_url,
        dest_dir,
        record.filename,
        source_id=record.id,
        timeout_seconds=config.data.http_timeout_seconds,
        max_retries=config.data.http_max_retries,
        retry_backoff_seconds=config.data.http_retry_backoff_seconds,
        user_agent=config.data.user_agent,
        force=force,
    )

    entries = [_entry_from_download(record, result)]
    if result.path.suffix == ".zip":
        for member_path in extract_zip_safely(result.path, dest_dir, force=force):
            entries.append(_entry_for_extracted(record, member_path, result.retrieved_at_utc))
    return entries


def _fetch_bcb(
    record: SourceRecord, config: Config, force: bool, start: str | None, end: str | None
) -> list[ManifestEntry]:
    if record.filename is None:
        raise BcbClientError(f"{record.id}: registry entry has no filename.")

    code = int(record.id.rsplit("-", 1)[-1])
    start_date = start or config.data.bcb_default_start_date
    end_date = end or datetime.now(UTC).strftime("%d/%m/%Y")

    result = fetch_series(
        code,
        start_date,
        end_date,
        timeout_seconds=config.data.http_timeout_seconds,
        max_retries=config.data.http_max_retries,
        retry_backoff_seconds=config.data.http_retry_backoff_seconds,
        user_agent=config.data.user_agent,
        max_days_per_request=config.data.bcb_max_days_per_request,
    )

    dest_dir = Path(config.data.raw_dir) / _RAW_SUBDIR_BY_SOURCE[record.id]
    dest_path = write_bytes_atomically(
        result.raw_json.encode("utf-8"), dest_dir, record.filename, force=force
    )

    return [
        ManifestEntry(
            source_id=record.id,
            relative_path=_relative_to_cwd(dest_path),
            filename=dest_path.name,
            size_bytes=dest_path.stat().st_size,
            sha256=compute_sha256(dest_path),
            retrieved_at_utc=result.retrieved_at_utc,
            url=result.final_url,
            format="json",
            num_rows=result.num_observations,
            num_columns=2,
            verification_status="unverified",
            source_version_or_date=f"{start_date} to {end_date}",
            license=record.license,
            notes=f"BCB SGS series {code}, {result.num_observations} observation(s).",
        )
    ]


def _fetch_one(
    record: SourceRecord, config: Config, force: bool, start: str | None, end: str | None
) -> list[ManifestEntry]:
    if record.acquisition_method == AcquisitionMethod.KAGGLE_API:
        raise DownloadError(
            f"{record.id}: BLOCKED_REQUIRES_USER_ACCESS. {record.restrictions} "
            "See data/metadata/licenses/kaggle-home-credit-notes.md for details. "
            "This project will not bypass authentication or request credentials."
        )
    if record.acquisition_method == AcquisitionMethod.HTTP_GET:
        return _fetch_http(record, config, force)
    if record.acquisition_method == AcquisitionMethod.BCB_SGS:
        return _fetch_bcb(record, config, force, start, end)
    raise DownloadError(
        f"{record.id}: unsupported acquisition method '{record.acquisition_method}'."
    )


def _merge_manifest_entries(
    existing: list[ManifestEntry], new: list[ManifestEntry]
) -> list[ManifestEntry]:
    replaced_paths = {entry.relative_path for entry in new}
    kept = [entry for entry in existing if entry.relative_path not in replaced_paths]
    return kept + new


def _cmd_data_fetch(source: str, force: bool, start: str | None, end: str | None) -> int:
    try:
        config = load_config()
        records = load_registry(REGISTRY_PATH)
    except (ConfigError, RegistryError) as exc:
        print(f"Error: {exc}")
        return 1

    if source == "bcb-sgs":
        targets = [r for r in records if r.acquisition_method == AcquisitionMethod.BCB_SGS]
        if not targets:
            print("No BCB SGS sources registered.")
            return 1
    else:
        try:
            targets = [get_source(records, source)]
        except RegistryError as exc:
            print(f"Error: {exc}")
            return 1

    existing_entries = read_manifest(MANIFEST_PATH) if MANIFEST_PATH.is_file() else []
    new_entries: list[ManifestEntry] = []
    had_error = False

    for record in targets:
        print(f"Fetching {record.id} ({record.acquisition_method.value})...")
        try:
            entries = _fetch_one(record, config, force, start, end)
        except (DownloadError, BcbClientError) as exc:
            print(f"  FAILED: {exc}")
            had_error = True
            continue
        new_entries.extend(entries)
        for entry in entries:
            print(
                f"  -> {entry.relative_path} "
                f"({entry.size_bytes} bytes, sha256={entry.sha256[:12]}...)"
            )

    if new_entries:
        merged = _merge_manifest_entries(existing_entries, new_entries)
        write_manifest(merged, MANIFEST_PATH)
        print(f"\nManifest updated: {MANIFEST_PATH} ({len(merged)} entry/entries).")

    return 1 if had_error else 0


# --- data verify ---------------------------------------------------------------


def _cmd_data_verify(source: str | None) -> int:
    if not MANIFEST_PATH.is_file():
        print(f"No manifest found at {MANIFEST_PATH} - nothing to verify yet.")
        print("Run 'credlens data fetch --source <id>' first.")
        return 1

    try:
        results = verify_manifest(MANIFEST_PATH, Path.cwd())
    except ManifestError as exc:
        print(f"Error: {exc}")
        return 1

    if source:
        results = [(entry, status) for entry, status in results if entry.source_id == source]
        if not results:
            print(f"No manifest entries found for source '{source}'.")
            return 1

    print("CredLens data verify")
    print("=" * 21)
    has_problem = False
    for entry, status in results:
        print(f"[{status:>8}] {entry.source_id:<22} {entry.relative_path}")
        if status != "OK":
            has_problem = True

    print()
    print(f"Result: {'FAIL' if has_problem else 'OK'} ({len(results)} file(s) checked)")
    return 1 if has_problem else 0


# --- data audit ------------------------------------------------------------------


def _load_schema_if_present(source_id: str) -> DatasetSchema | None:
    path = SCHEMAS_DIR / f"{source_id}.yaml"
    if not path.is_file():
        return None
    try:
        return load_schema(path)
    except SchemaError:
        return None


def _load_dataframe_for_audit(
    source_id: str, entries: list[ManifestEntry]
) -> tuple[pd.DataFrame | None, str]:
    repo_root = Path.cwd()

    if source_id == "uci-default-credit":
        entry = next((e for e in entries if e.filename.endswith(".csv")), None)
        if entry is None:
            return None, "no .csv file recorded in the manifest for this source"
        return pd.read_csv(repo_root / entry.relative_path), entry.relative_path

    if source_id == "south-german-credit":
        entry = next((e for e in entries if e.filename.endswith(".asc")), None)
        if entry is None:
            return None, "no extracted .asc file recorded in the manifest (re-run fetch?)"
        return pd.read_csv(repo_root / entry.relative_path, sep=r"\s+"), entry.relative_path

    if source_id.startswith("bcb-sgs-"):
        entry = next((e for e in entries if e.filename.endswith(".json")), None)
        if entry is None:
            return None, "no .json file recorded in the manifest for this source"
        raw = json.loads((repo_root / entry.relative_path).read_text(encoding="utf-8"))
        return pd.DataFrame(raw), entry.relative_path

    return None, f"no audit loader implemented for source '{source_id}'"


def _update_row_col_counts(
    entries: list[ManifestEntry], relative_path: str, num_rows: int, num_columns: int
) -> list[ManifestEntry]:
    return [
        replace(entry, num_rows=num_rows, num_columns=num_columns, verification_status="audited")
        if entry.relative_path == relative_path
        else entry
        for entry in entries
    ]


def _cmd_data_audit(source: str | None) -> int:
    try:
        load_registry(REGISTRY_PATH)  # validated for side effect: raise if the registry is broken
    except RegistryError as exc:
        print(f"Error: {exc}")
        return 1

    if not MANIFEST_PATH.is_file():
        print("No manifest found - nothing has been acquired yet.")
        print("Run 'credlens data fetch --source <id>' first. This command never downloads data.")
        return 1

    entries = read_manifest(MANIFEST_PATH)
    if source:
        entries = [e for e in entries if e.source_id == source]
        if not entries:
            print(f"No manifest entries found for source '{source}'.")
            return 1

    entries_by_source: dict[str, list[ManifestEntry]] = {}
    for entry in entries:
        entries_by_source.setdefault(entry.source_id, []).append(entry)

    all_manifest_entries = read_manifest(MANIFEST_PATH)
    all_reports: dict[str, object] = {}

    print("CredLens data audit")
    print("=" * 20)

    for source_id in sorted(entries_by_source):
        df, path_or_reason = _load_dataframe_for_audit(source_id, entries_by_source[source_id])
        if df is None:
            print(f"\n{source_id}: skipped - {path_or_reason}")
            continue

        report = audit_dataframe(
            df,
            source_id=source_id,
            schema=_load_schema_if_present(source_id),
            documented_no_missing_values=source_id in _DOCUMENTED_NO_MISSING_VALUES,
            known_id_columns=_KNOWN_ID_COLUMNS.get(source_id, ()),
        )
        all_reports[source_id] = report.to_dict()
        all_manifest_entries = _update_row_col_counts(
            all_manifest_entries,
            path_or_reason,
            report.profile.num_rows,
            report.profile.num_columns,
        )

        print(
            f"\n{source_id}  ({report.profile.num_rows} rows x {report.profile.num_columns} cols)"
        )
        if not report.findings:
            print("  No findings.")
        counts: dict[str, int] = {}
        for finding in report.findings:
            counts[finding.category] = counts.get(finding.category, 0) + 1
        for category, count in sorted(counts.items()):
            print(f"  {category}: {count}")

    write_manifest(all_manifest_entries, MANIFEST_PATH)

    AUDIT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at_utc": datetime.now(UTC).isoformat(), "sources": all_reports}
    AUDIT_METRICS_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {AUDIT_METRICS_PATH}")

    return 0


# --- contracts -----------------------------------------------------------------


def _cmd_contracts_list() -> int:
    try:
        contracts = load_all_contracts(CONTRACTS_RAW_DIR, CONTRACTS_OPERATIONAL_DIR)
    except ContractsRegistryError as exc:
        print(f"Error: {exc}")
        return 1

    print("CredLens data contracts")
    print("=" * 24)
    print(f"{'NAME':<28} {'VER':<4} {'CLASSIFICATION':<22} {'STATUS':<10} GRAIN")
    for name, contract in sorted(contracts.items()):
        print(
            f"{name:<28} {contract.version:<4} {contract.classification.value:<22} "
            f"{contract.status.value:<10} {contract.grain}"
        )
    return 0


def _cmd_contracts_show(name: str) -> int:
    try:
        contracts = load_all_contracts(CONTRACTS_RAW_DIR, CONTRACTS_OPERATIONAL_DIR)
        contract = get_contract(contracts, name)
    except ContractsRegistryError as exc:
        print(f"Error: {exc}")
        return 1

    print(f"{contract.name}  (v{contract.version}, {contract.status.value})")
    print("=" * (len(contract.name) + 20))
    print(f"Classification: {contract.classification.value}")
    print(f"Grain:          {contract.grain}")
    print(f"Owner:          {contract.owner}")
    print(f"Description:    {contract.description.strip()}")
    print(f"Primary key:    {', '.join(contract.primary_key) or '(none)'}")

    if contract.foreign_keys:
        print("Foreign keys:")
        for fk in contract.foreign_keys:
            print(
                f"  {fk.column} -> {fk.references_contract}.{fk.references_column} "
                f"({fk.severity.value})"
            )

    print(f"Columns ({len(contract.columns)}):")
    for column in contract.columns:
        nullable = "nullable" if column.nullable else "not null"
        modeling = "modeling-ok" if column.available_for_modeling else "not for modeling"
        print(
            f"  {column.name:<24} {column.type.value:<12} {nullable:<10} "
            f"{modeling:<18} {column.sensitivity.value}"
        )

    if contract.business_rules:
        print(f"Business rules ({len(contract.business_rules)}):")
        for rule in contract.business_rules:
            print(f"  [{rule.severity.value}] {rule.code}: {rule.description}")

    return 0


def _cmd_contracts_validate(contract_name: str, path_str: str, mode: str) -> int:
    try:
        contracts = load_all_contracts(CONTRACTS_RAW_DIR, CONTRACTS_OPERATIONAL_DIR)
        contract = get_contract(contracts, contract_name)
    except ContractsRegistryError as exc:
        print(f"Error: {exc}")
        return 1

    try:
        report = validate_contract(contract, Path(path_str), mode=mode, all_contracts=contracts)
    except ValidationRunError as exc:
        print(f"Error: {exc}")
        return 1

    print(format_report(report))

    if mode == "strict":
        return 1 if report.has_errors else 0
    return 0  # audit mode is diagnostic - it never fails the command itself.


# --- synthetic -----------------------------------------------------------------


def _cmd_synthetic_scenarios() -> int:
    try:
        blueprints = load_all_blueprints(SYNTHETIC_SCENARIOS_DIR)
    except BlueprintError as exc:
        print(f"Error: {exc}")
        return 1

    if not blueprints:
        print(f"No scenario blueprints found in '{SYNTHETIC_SCENARIOS_DIR}'.")
        return 0

    print("CredLens synthetic scenarios")
    print("=" * 28)
    print(f"{'SCENARIO':<24} {'STATUS':<20} NAME")
    for scenario_id, blueprint in sorted(blueprints.items()):
        print(f"{scenario_id:<24} {blueprint.status.value:<20} {blueprint.name}")
    return 0


def _cmd_synthetic_plan() -> int:
    try:
        contracts = load_all_contracts(CONTRACTS_RAW_DIR, CONTRACTS_OPERATIONAL_DIR)
    except ContractsRegistryError as exc:
        print(f"Error: {exc}")
        return 1
    try:
        blueprints = load_all_blueprints(SYNTHETIC_SCENARIOS_DIR)
    except BlueprintError as exc:
        print(f"Error: {exc}")
        return 1

    operational = [
        c for c in contracts.values() if c.classification.value == "synthetic_operational"
    ]
    total_rules = sum(len(c.business_rules) for c in contracts.values())
    calibration_pending = sum(
        1 for bp in blueprints.values() if bp.status == "requires_calibration"
    )

    print("CredLens synthetic-generation readiness")
    print("=" * 40)
    print(f"Operational contracts defined:              {len(operational)}")
    print(f"Business rules implemented across contracts: {total_rules}")
    print(f"Scenario blueprints defined:                 {len(blueprints)}")
    print(f"Blueprints still requiring calibration:      {calibration_pending}/{len(blueprints)}")
    print()
    print(
        "credlens synthetic generate --scenario baseline --scale {smoke,sample,portfolio} --seed N"
    )
    print("is implemented as of Phase 4A. Every other scenario remains requires_calibration.")
    return 0


def _cmd_synthetic_validate_blueprints() -> int:
    if not SYNTHETIC_SCENARIOS_DIR.is_dir():
        print(f"No blueprint directory found at '{SYNTHETIC_SCENARIOS_DIR}'.")
        return 1

    paths = sorted(SYNTHETIC_SCENARIOS_DIR.glob("*.blueprint.yaml"))
    if not paths:
        print(f"No blueprint files found in '{SYNTHETIC_SCENARIOS_DIR}'.")
        return 1

    print("CredLens blueprint validation")
    print("=" * 30)
    any_failed = False
    for path in paths:
        try:
            blueprint = load_blueprint(path)
        except BlueprintError as exc:
            print(f"[FAIL] {path.name}: {exc}")
            any_failed = True
            continue
        counts = blueprint.parameter_counts()
        print(
            f"[  OK] {blueprint.scenario_id} ({blueprint.status.value}): "
            f"{counts[ParameterStatus.SPECIFIED]} specified, "
            f"{counts[ParameterStatus.PENDING]} pending, "
            f"{counts[ParameterStatus.REQUIRES_CALIBRATION]} requires_calibration"
        )

    print()
    print(f"Result: {'FAIL' if any_failed else 'OK'}")
    return 1 if any_failed else 0


def _cmd_synthetic_generate(scenario: str, scale: str, seed: int, force: bool) -> int:
    from credlens.generation.orchestrator import (
        GenerationError,
        RunAlreadyExistsError,
        ScenarioNotCalibratedError,
        generate_baseline,
    )

    try:
        outcome = generate_baseline(scenario=scenario, scale_name=scale, seed=seed, force=force)
    except ScenarioNotCalibratedError as exc:
        print(f"Error: {exc}")
        return 1
    except RunAlreadyExistsError as exc:
        print(f"Error: {exc}")
        return 1
    except GenerationError as exc:
        print(f"Error: {exc}")
        return 1
    except Exception as exc:
        logger.exception("Unhandled error during synthetic generation")
        print(f"Error: generation failed unexpectedly ({type(exc).__name__}). See logs for detail.")
        return 1

    print(f"generation_run_id: {outcome.generation_run_id}")
    print(f"status:            {outcome.status}")
    print(f"operational dir:   {outcome.operational_dir}")
    print(f"truth dir:         {outcome.truth_dir}")
    print(f"contracts passed:  {outcome.validation.contracts_passed}")
    print(f"pii safe:          {outcome.validation.pii_safe}")
    print(f"statistical checks passed: {outcome.validation.statistical_passed}")
    if outcome.status != "completed":
        print(
            "Run FAILED validation - not promoted. See contract_validation.json in the "
            "run's staging directory."
        )
        return 1
    return 0


def _resolve_run_dir(config_output_dir: str, run_id: str) -> Path | None:
    """Path-traversal-safe resolution of a user-supplied --run-id, shared
    by validate/inspect/manifest - mirrors the same protection
    generate's own writers.resolve_within_directory applies."""
    from credlens.generation.writers import PathSafetyError, resolve_within_directory

    try:
        return resolve_within_directory(Path(config_output_dir), run_id)
    except PathSafetyError:
        return None


def _cmd_synthetic_validate_run(run_id: str) -> int:
    from credlens.generation.config import load_generation_config

    try:
        config = load_generation_config()
    except Exception as exc:
        print(f"Error: could not load generation config: {exc}")
        return 1

    run_base = _resolve_run_dir(config.output.operational_dir, run_id)
    if run_base is None:
        print(f"Error: invalid run id '{run_id}'.")
        return 1
    run_dir = run_base / "operational"
    if not run_dir.is_dir():
        print(f"Error: no run found at '{run_dir}'.")
        return 1

    try:
        contracts = load_all_contracts(CONTRACTS_RAW_DIR, CONTRACTS_OPERATIONAL_DIR)
    except ContractsRegistryError as exc:
        print(f"Error: {exc}")
        return 1

    # Every contract defined under contracts/operational/ is something
    # the generator can legitimately produce - not just the ones
    # classified synthetic_operational (fairness_attributes is
    # evaluation_only, macro_context_monthly is public_market_context,
    # generation_runs is technical_metadata - all three are real files
    # in every run and must be validated too).
    operational_names = {path.stem for path in CONTRACTS_OPERATIONAL_DIR.glob("*.yaml")}

    any_errors = False
    for name, contract in sorted(contracts.items()):
        if name not in operational_names:
            continue
        try:
            report = validate_contract(contract, run_dir, mode="strict", all_contracts=contracts)
        except ValidationRunError:
            continue  # this contract's file isn't part of this run - not an error
        print(format_report(report))
        if report.has_errors:
            any_errors = True

    print()
    print(f"Result: {'FAIL' if any_errors else 'OK'}")
    return 1 if any_errors else 0


def _cmd_synthetic_inspect(run_id: str) -> int:
    from credlens.generation.config import load_generation_config

    try:
        config = load_generation_config()
    except Exception as exc:
        print(f"Error: could not load generation config: {exc}")
        return 1

    run_dir = _resolve_run_dir(config.output.operational_dir, run_id)
    if run_dir is None:
        print(f"Error: invalid run id '{run_id}'.")
        return 1
    operational_dir = run_dir / "operational"
    if not operational_dir.is_dir():
        print(f"Error: no run found at '{operational_dir}'.")
        return 1

    print(f"CredLens synthetic run: {run_id}")
    print("=" * (24 + len(run_id)))
    for path in sorted(operational_dir.glob("*.parquet")):
        df = pd.read_parquet(path)
        print(f"{path.stem:<28} {len(df):>8} rows")

    summary_path = run_dir / "generation_summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        print()
        print(f"status:                     {summary.get('status')}")
        print(f"contracts_passed:           {summary.get('contracts_passed')}")
        print(f"statistical_checks_passed:  {summary.get('statistical_checks_passed')}")
        print(f"pii_safe:                   {summary.get('pii_safe')}")
    return 0


def _cmd_synthetic_manifest(run_id: str) -> int:
    from credlens.generation.config import load_generation_config

    try:
        config = load_generation_config()
    except Exception as exc:
        print(f"Error: could not load generation config: {exc}")
        return 1

    run_dir = _resolve_run_dir(config.output.operational_dir, run_id)
    if run_dir is None:
        print(f"Error: invalid run id '{run_id}'.")
        return 1
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        print(f"Error: no manifest found at '{manifest_path}'.")
        return 1

    print(manifest_path.read_text(encoding="utf-8"))
    return 0


def _cmd_synthetic_generate_suite(scale: str, seed: int, force: bool) -> int:
    from credlens.generation.config import ConfigError, CrnIncompatibleError
    from credlens.generation.orchestrator import GenerationError
    from credlens.generation.suite import generate_suite

    try:
        outcome = generate_suite(scale_name=scale, seed=seed, force=force)
    except (GenerationError, ConfigError, CrnIncompatibleError) as exc:
        print(f"Error: {exc}")
        return 1
    except Exception as exc:
        logger.exception("Unhandled error during suite generation")
        print(f"Error: suite generation failed unexpectedly ({type(exc).__name__}). See logs.")
        return 1

    print(f"suite_id:         {outcome.suite_id}")
    print(f"baseline_run_id:  {outcome.baseline_run_id}")
    print("scenario_run_ids:")
    for scenario, run_id in outcome.scenario_run_ids.items():
        print(f"  {scenario:<24} {run_id}")
    any_failed = any(o.status != "completed" for o in outcome.outcomes.values())
    print(f"manifest:         {outcome.manifest_path}")
    if any_failed:
        print("One or more runs in this suite did not complete successfully.")
        return 1
    return 0


def _cmd_synthetic_compare(baseline_run_id: str, candidate_run_id: str) -> int:
    from credlens.generation.comparison import compare_metrics, compute_metrics
    from credlens.generation.config import load_generation_config

    try:
        config = load_generation_config()
    except Exception as exc:
        print(f"Error: could not load generation config: {exc}")
        return 1

    baseline_dir = _resolve_run_dir(config.output.operational_dir, baseline_run_id)
    candidate_dir = _resolve_run_dir(config.output.operational_dir, candidate_run_id)
    if baseline_dir is None or candidate_dir is None:
        print("Error: invalid run id.")
        return 1
    baseline_op = baseline_dir / "operational"
    candidate_op = candidate_dir / "operational"
    if not baseline_op.is_dir() or not candidate_op.is_dir():
        print("Error: one or both runs were not found.")
        return 1

    baseline_metrics = compute_metrics(baseline_run_id, baseline_op)
    candidate_metrics = compute_metrics(candidate_run_id, candidate_op)
    comparisons = compare_metrics(baseline_metrics, candidate_metrics)

    print(f"Comparing {baseline_run_id} (baseline) vs {candidate_run_id} (candidate)")
    print("=" * 70)
    print(f"{'metric':<20} {'baseline':>12} {'candidate':>12} {'delta':>12}")
    for c in comparisons:
        print(
            f"{c.metric:<20} {c.baseline_value:>12.4f} {c.candidate_value:>12.4f} {c.delta:>12.4f}"
        )
    return 0


def _cmd_synthetic_validate_suite(suite_id: str) -> int:
    from credlens.generation.suite import SuiteError, load_suite_manifest

    try:
        manifest = load_suite_manifest(suite_id)
    except SuiteError as exc:
        print(f"Error: {exc}")
        return 1

    run_ids = [str(manifest["baseline_run_id"])]
    scenario_run_ids = manifest.get("scenario_run_ids", {})
    if isinstance(scenario_run_ids, dict):
        run_ids.extend(str(v) for v in scenario_run_ids.values())

    print(f"CredLens suite validation: {suite_id}")
    print("=" * (28 + len(suite_id)))
    any_errors = False
    for run_id in run_ids:
        exit_code = _cmd_synthetic_validate_run(run_id)
        if exit_code != 0:
            any_errors = True

    scenarios = manifest.get("scenarios", {})
    if isinstance(scenarios, dict):
        for scenario, report in scenarios.items():
            if not isinstance(report, dict):
                continue
            crn_ok = report.get("population_crn_preserved")
            print(f"\n{scenario}: population_crn_preserved={crn_ok}")
            if not crn_ok:
                any_errors = True
            for check in report.get("directional_checks", []):
                status = "OK" if check["passed"] else "FAIL"
                print(f"  [{status}] {check['name']}: {check['detail']}")
                if not check["passed"]:
                    any_errors = True

    print()
    print(f"Result: {'FAIL' if any_errors else 'OK'}")
    return 1 if any_errors else 0


def _cmd_synthetic_monte_carlo(scenario: str, scale: str, n_seeds: int, start_seed: int) -> int:
    from credlens.generation.config import ConfigError, CrnIncompatibleError
    from credlens.generation.montecarlo import run_monte_carlo, write_monte_carlo_report
    from credlens.generation.orchestrator import GenerationError

    seeds = [start_seed + i for i in range(n_seeds)]
    try:
        result = run_monte_carlo(scenario=scenario, scale_name=scale, seeds=seeds)
    except (GenerationError, ConfigError, CrnIncompatibleError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1
    except Exception as exc:
        logger.exception("Unhandled error during Monte Carlo run")
        print(f"Error: Monte Carlo failed unexpectedly ({type(exc).__name__}). See logs.")
        return 1

    report_path = Path("reports/synthetic_validation/monte_carlo_summary.json")
    write_monte_carlo_report(report_path, result)

    print(f"Monte Carlo: {scenario} @ {scale}, {len(seeds)} seed(s) {seeds}")
    print("=" * 60)
    print(f"{'metric':<20} {'mean_delta':>12} {'stdev':>10} {'expected':>10} {'frac_ok':>8}")
    for name, summary in result.metric_summaries.items():
        frac = (
            f"{summary.fraction_in_expected_direction:.2f}"
            if summary.fraction_in_expected_direction is not None
            else "n/a"
        )
        print(
            f"{name:<20} {summary.mean_delta:>12.4f} {summary.stdev_delta:>10.4f} "
            f"{summary.expected_direction or '-':>10} {frac:>8}"
        )
    print(f"\ncontract_failures: {result.contract_failures}")
    print(f"Report: {report_path}")
    return 1 if result.contract_failures else 0


def _cmd_synthetic_profile(scenario: str, scale: str, seed: int) -> int:
    from credlens.generation.config import ConfigError
    from credlens.generation.orchestrator import GenerationError
    from credlens.generation.profiling import profile_generation

    try:
        result = profile_generation(scenario=scenario, scale_name=scale, seed=seed)
    except (GenerationError, ConfigError) as exc:
        print(f"Error: {exc}")
        return 1
    except Exception as exc:
        logger.exception("Unhandled error during profiling")
        print(f"Error: profiling failed unexpectedly ({type(exc).__name__}). See logs.")
        return 1

    print(f"CredLens synthetic profile: {scenario} @ {scale}, seed={seed}")
    print("=" * 60)
    print(f"duration_seconds (clean run):  {result.duration_seconds:.3f}")
    print(f"peak_memory_mb (tracemalloc):  {result.peak_memory_mb:.2f}")
    print(f"global_content_hash:           {result.global_content_hash}")
    print("table_row_counts:")
    for name, count in sorted(result.table_row_counts.items()):
        print(f"  {name:<28} {count:>8}")
    print("\nTop functions by cumulative time (separate cProfile run, has overhead):")
    print(result.top_functions_by_cumulative_time)
    return 0


# --- warehouse (Phase 5) ------------------------------------------------------


def _cmd_warehouse_prepare(run_id: str | None, suite_id: str | None, as_json: bool) -> int:
    from credlens.warehouse.sources import SourceSelectionError, resolve_sources

    try:
        sources = resolve_sources(run_id=run_id, suite_id=suite_id)
    except SourceSelectionError as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps([s.to_dict() for s in sources], indent=2))
        return 0

    print("CredLens warehouse prepare")
    print("=" * 26)
    for s in sources:
        print(f"run_id:              {s.run_id}")
        print(f"  suite_id:          {s.suite_id or '(none)'}")
        print(f"  scenario:          {s.scenario}")
        print(f"  seed / scale:      {s.seed} / {s.scale}")
        print(f"  generator_version: {s.generator_version}")
        print(f"  config_hash:       {s.config_hash[:16]}...")
        print(f"  global_content_hash: {s.global_content_hash[:16]}...")
        print(f"  source_path:       {s.source_path}")
        print(f"  tables:            {len(s.row_counts)}")
    print()
    print(f"Result: OK ({len(sources)} run(s) safe to load)")
    return 0


def _cmd_warehouse_build(
    run_id: str | None, suite_id: str | None, build_id: str | None, force: bool, as_json: bool
) -> int:
    from credlens.warehouse.build import BuildError, run_build
    from credlens.warehouse.sources import SourceSelectionError

    try:
        manifest = run_build(
            run_id=run_id, suite_id=suite_id, build_id=build_id, force=force, quiet=as_json
        )
    except SourceSelectionError as exc:
        print(f"Error: {exc}")
        return 1
    except BuildError as exc:
        print(f"Error: {exc}")
        return 1
    except Exception as exc:
        logger.exception("Unhandled error during warehouse build")
        print(f"Error: warehouse build failed unexpectedly ({type(exc).__name__}). See logs.")
        return 1

    if as_json:
        print(json.dumps(manifest.to_dict(), indent=2))
    else:
        print(f"build_id:               {manifest.build_id}")
        print(f"db_path:                {manifest.db_path}")
        print(f"included_run_ids:       {', '.join(manifest.included_run_ids)}")
        print(f"dbt_version:            {manifest.dbt_version}")
        print(f"duckdb_version:         {manifest.duckdb_version}")
        print(
            f"tests:                  {manifest.test_results.get('passed')} passed, "
            f"{manifest.test_results.get('failed')} failed, "
            f"{manifest.test_results.get('errored')} errored, "
            f"{manifest.test_results.get('skipped')} skipped"
        )
        print(f"analytical_fingerprint: {manifest.analytical_fingerprint}")
        print(f"total_duration_seconds: {manifest.step_durations.get('total', 0):.2f}")
        print(f"final_status:           {manifest.final_status}")

    return 0 if manifest.final_status == "success" else 1


def _cmd_warehouse_test(build_id: str, as_json: bool) -> int:
    from credlens.warehouse.build import BuildError, run_tests

    try:
        results = run_tests(build_id, quiet=as_json)
    except BuildError as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(results, indent=2))
    else:
        print(f"CredLens warehouse test: {build_id}")
        print("=" * (26 + len(build_id)))
        print(f"passed:  {results['passed']}")
        print(f"failed:  {results['failed']}")
        print(f"errored: {results['errored']}")
        print(f"skipped: {results['skipped']}")
        if results["failures"]:
            print("failures:")
            for name in results["failures"]:
                print(f"  - {name}")

    return 0 if results.get("success") else 1


def _cmd_warehouse_status(build_id: str, as_json: bool) -> int:
    from credlens.warehouse.build import BuildError, load_build_manifest

    try:
        manifest = load_build_manifest(build_id)
    except BuildError as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(manifest.to_dict(), indent=2))
        return 0

    print(f"CredLens warehouse status: {build_id}")
    print("=" * (27 + len(build_id)))
    print(f"final_status:           {manifest.final_status}")
    print(f"built_at:                {manifest.built_at}")
    print(f"db_path:                {manifest.db_path}")
    print(f"run_id / suite_id:      {manifest.run_id} / {manifest.suite_id}")
    print(f"included_run_ids:       {', '.join(manifest.included_run_ids)}")
    print(f"code_version:           {manifest.code_version}")
    print(f"dbt_version:            {manifest.dbt_version}")
    print(f"duckdb_version:         {manifest.duckdb_version}")
    print(f"model_row_counts:       {len(manifest.model_row_counts)} materialized table(s)")
    print(
        f"tests:                  {manifest.test_results.get('passed')} passed / "
        f"{manifest.test_results.get('failed')} failed / "
        f"{manifest.test_results.get('errored')} errored"
    )
    print(f"analytical_fingerprint: {manifest.analytical_fingerprint}")
    return 0 if manifest.final_status == "success" else 1


def _cmd_warehouse_query(build_id: str, name: str, as_json: bool) -> int:
    from credlens.warehouse.build import BuildError, load_build_manifest
    from credlens.warehouse.integrity import RawIntegrityError
    from credlens.warehouse.queries import QueryError, run_named_query

    try:
        manifest = load_build_manifest(build_id)
    except BuildError as exc:
        print(f"Error: {exc}")
        return 1

    try:
        columns, rows = run_named_query(Path(manifest.db_path), name, manifest.sources)
    except RawIntegrityError as exc:
        print(f"Error: {exc}")
        return 1
    except QueryError as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        payload = [dict(zip(columns, row, strict=True)) for row in rows]
        print(json.dumps(payload, indent=2, default=str))
        return 0

    print(f"CredLens warehouse query: {name} (build {build_id})")
    print("=" * 40)
    print(" | ".join(columns))
    for row in rows:
        print(" | ".join(str(v) for v in row))
    print(f"\n{len(rows)} row(s).")
    return 0


def _cmd_warehouse_reconcile(build_id: str, as_json: bool) -> int:
    from credlens.warehouse.build import BuildError, load_build_manifest
    from credlens.warehouse.integrity import RawIntegrityError
    from credlens.warehouse.reconciliation import run_reconciliation

    try:
        manifest = load_build_manifest(build_id)
    except BuildError as exc:
        print(f"Error: {exc}")
        return 1

    try:
        results = run_reconciliation(Path(manifest.db_path), manifest.sources)
    except RawIntegrityError as exc:
        print(f"Error: {exc}")
        return 1
    any_failed = any(not r.passed for r in results)

    if as_json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
        return 1 if any_failed else 0

    print(f"CredLens warehouse reconcile: {build_id}")
    print("=" * (29 + len(build_id)))
    for r in results:
        status = "OK" if r.passed else "MISMATCH"
        print(f"[{status:>8}] {r.name:<20} {r.run_id:<40} {r.detail}")
    print()
    print(f"Result: {'FAIL' if any_failed else 'OK'} ({len(results)} check(s))")
    return 1 if any_failed else 0


def _cmd_warehouse_docs(build_id: str) -> int:
    from credlens.warehouse.build import BuildError, generate_docs

    try:
        index_path = generate_docs(build_id)
    except BuildError as exc:
        print(f"Error: {exc}")
        return 1

    print(f"dbt docs generated: {index_path}")
    print("Open that file in a browser to view the static docs site (not served by this CLI).")
    return 0


# --- analysis (Phase 6) ------------------------------------------------------


def _cmd_analysis_validate(build_id: str, as_json: bool) -> int:
    from credlens.analysis.validation import AnalysisValidationError, validate_build_for_analysis

    try:
        manifest = validate_build_for_analysis(build_id)
    except AnalysisValidationError as exc:
        if as_json:
            print(json.dumps({"build_id": build_id, "valid": False, "error": str(exc)}, indent=2))
        else:
            print(f"Error: {exc}")
        return 1

    if as_json:
        print(
            json.dumps(
                {
                    "build_id": manifest.build_id,
                    "valid": True,
                    "suite_id": manifest.suite_id,
                    "analytical_fingerprint": manifest.analytical_fingerprint,
                    "test_results": manifest.test_results,
                },
                indent=2,
            )
        )
        return 0

    print(f"CredLens analysis validate: {build_id}")
    print("=" * (26 + len(build_id)))
    print(f"suite_id:               {manifest.suite_id}")
    print(f"analytical_fingerprint: {manifest.analytical_fingerprint}")
    print(
        f"dbt tests:              {manifest.test_results.get('passed')} passed / "
        f"{manifest.test_results.get('failed')} failed / "
        f"{manifest.test_results.get('errored')} errored"
    )
    print("raw source integrity:   OK (re-verified against build manifest)")
    print()
    print("Result: OK (safe to analyze)")
    return 0


def _cmd_analysis_run(
    build_id: str,
    output_dir: str | None,
    force: bool,
    no_benchmark: bool,
    multiseed: bool,
    multiseed_scenario: str,
    multiseed_scale: str,
    multiseed_seeds: int,
    insights: bool,
    as_json: bool,
) -> int:
    from credlens.analysis.runner import AnalysisRunError, run_analysis
    from credlens.analysis.validation import AnalysisValidationError

    resolved_output_dir = Path(output_dir) if output_dir else ANALYSIS_OUTPUT_DIR
    if (resolved_output_dir / "manifest.json").exists() and not force:
        print(
            f"Error: an analysis already exists at '{resolved_output_dir}'. Pass --force to "
            "overwrite it, or --output-dir to write elsewhere."
        )
        return 1

    try:
        result = run_analysis(
            build_id=build_id,
            output_dir=resolved_output_dir,
            include_benchmark=not no_benchmark,
            include_multiseed=multiseed,
            multiseed_seeds=multiseed_seeds,
            multiseed_scenario=multiseed_scenario,
            include_insights=insights,
            multiseed_scale=multiseed_scale,
        )
    except AnalysisValidationError as exc:
        print(f"Error: {exc}")
        return 1
    except AnalysisRunError as exc:
        print(f"Error: {exc}")
        return 1
    except Exception as exc:
        logger.exception("Unhandled error during analysis run")
        print(f"Error: analysis run failed unexpectedly ({type(exc).__name__}). See logs.")
        return 1

    if as_json:
        print(json.dumps(result.manifest.to_dict(), indent=2))
    else:
        print(f"analysis_id:     {result.analysis_id}")
        print(f"output_dir:      {result.output_dir}")
        print(f"tables written:  {len(result.manifest.tables_written)}")
        print(f"figures written: {len(result.manifest.figures_written)}")
        print(f"reports hashed:  {len(result.manifest.reports_written)}")
        print(f"executive_summary (en):     {result.executive_summary_en}")
        print(f"executive_summary (pt-BR):  {result.executive_summary_pt}")
        print(f"technical_report (en):      {result.technical_report_en}")
        print(f"technical_report (pt-BR):   {result.technical_report_pt}")
        if result.manifest.warnings:
            print("warnings:")
            for w in result.manifest.warnings:
                print(f"  - {w}")
        print(f"final_status:    {result.manifest.final_status}")

    return 0 if result.manifest.final_status == "success" else 1


def _cmd_analysis_scenarios(build_id: str, as_json: bool) -> int:
    from credlens.analysis import metrics
    from credlens.analysis.scenarios import composition_vs_performance
    from credlens.analysis.validation import AnalysisValidationError, validate_build_for_analysis

    try:
        build = validate_build_for_analysis(build_id)
    except AnalysisValidationError as exc:
        print(f"Error: {exc}")
        return 1
    if build.suite_id is None:
        print(f"Error: build '{build_id}' has no suite_id - nothing to compare scenarios against.")
        return 1

    with metrics.connect(Path(build.db_path)) as conn:
        scenario_cmp = metrics.scenario_comparison(conn, build.suite_id)
        composition = {}
        for scenario_name in ("policy_expansion", "policy_tightening"):
            with contextlib.suppress(ValueError):
                composition[scenario_name] = composition_vs_performance(
                    conn, build.suite_id, scenario_name
                ).to_dict()

    if as_json:
        print(
            json.dumps(
                {
                    "scenario_comparison": scenario_cmp.to_dict(orient="records"),
                    "composition_vs_performance": composition,
                },
                indent=2,
                default=str,
            )
        )
        return 0

    print(f"CredLens analysis scenarios: {build_id} (suite {build.suite_id})")
    print("=" * 60)
    print(scenario_cmp.to_string(index=False))
    print()
    for scenario_name, comp in composition.items():
        print(f"-- {scenario_name} composition vs. performance --")
        for k, v in comp.items():
            print(f"  {k}: {v}")
    return 0


def _cmd_analysis_benchmark(as_json: bool) -> int:
    from credlens.analysis.benchmark import profile_public_sources

    profiles = profile_public_sources()
    if as_json:
        print(json.dumps([p.to_dict() for p in profiles], indent=2))
        return 0

    if not profiles:
        print(
            "No public benchmark sources found (no acquired/manifested files). This is "
            "an optional appendix - see docs/dataset_selection.md."
        )
        return 0

    print("CredLens analysis benchmark (public data, kept separate from synthetic builds)")
    print("=" * 60)
    for p in profiles:
        print(f"source_id: {p.source_id}")
        print(f"  rows / columns: {p.num_rows} / {p.num_columns}")
        print(f"  missing-value findings: {p.missing_value_findings}")
        print(f"  domain findings: {p.domain_findings}")
        print(f"  context: {p.context}")
    return 0


def _load_analysis_manifest(output_dir: Path) -> dict[str, Any]:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"No analysis manifest found at '{manifest_path}'.")
    payload: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    return payload


def _cmd_analysis_status(output_dir: str | None, analysis_id: str | None, as_json: bool) -> int:
    resolved_output_dir = Path(output_dir) if output_dir else ANALYSIS_OUTPUT_DIR
    try:
        manifest = _load_analysis_manifest(resolved_output_dir)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return 1

    if analysis_id is not None and manifest.get("analysis_id") != analysis_id:
        print(
            f"Error: manifest at '{resolved_output_dir}' has analysis_id "
            f"'{manifest.get('analysis_id')}', not '{analysis_id}'."
        )
        return 1

    if as_json:
        print(json.dumps(manifest, indent=2))
        return 0

    print(f"CredLens analysis status: {resolved_output_dir}")
    print("=" * 40)
    print(f"analysis_id:            {manifest.get('analysis_id')}")
    print(f"build_id:                {manifest.get('build_id')}")
    print(f"warehouse_fingerprint:   {manifest.get('warehouse_fingerprint')}")
    print(f"queries_executed:        {len(manifest.get('queries_executed', []))}")
    print(f"tables_written:          {len(manifest.get('tables_written', {}))}")
    print(f"figures_written:         {len(manifest.get('figures_written', {}))}")
    print(f"warnings:                {len(manifest.get('warnings', []))}")
    print(f"final_status:            {manifest.get('final_status')}")
    return 0 if manifest.get("final_status") in ("success", "completed_with_warnings") else 1


def _cmd_analysis_reproduce(
    output_dir: str | None, analysis_id: str | None, reproduce_dir: str | None, as_json: bool
) -> int:
    from credlens.analysis.runner import AnalysisRunError, run_analysis
    from credlens.analysis.validation import AnalysisValidationError

    resolved_output_dir = Path(output_dir) if output_dir else ANALYSIS_OUTPUT_DIR
    try:
        original = _load_analysis_manifest(resolved_output_dir)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return 1

    if analysis_id is not None and original.get("analysis_id") != analysis_id:
        print(
            f"Error: manifest at '{resolved_output_dir}' has analysis_id "
            f"'{original.get('analysis_id')}', not '{analysis_id}'."
        )
        return 1

    resolved_reproduce_dir = (
        Path(reproduce_dir)
        if reproduce_dir
        else resolved_output_dir.parent / f"{resolved_output_dir.name}_reproduce"
    )

    original_parameters = original.get("parameters", {})
    try:
        result = run_analysis(
            build_id=original["build_id"],
            output_dir=resolved_reproduce_dir,
            **original_parameters,
        )
    except (AnalysisValidationError, AnalysisRunError) as exc:
        print(f"Error: {exc}")
        return 1

    reproduced = result.manifest.to_dict()
    mismatches = {
        name: {"original": original["tables_written"].get(name), "reproduced": h}
        for name, h in reproduced["tables_written"].items()
        if original["tables_written"].get(name) != h
    }
    mismatches |= {
        name: {"original": original["figures_written"].get(name), "reproduced": h}
        for name, h in reproduced["figures_written"].items()
        if original["figures_written"].get(name) != h
    }
    # Phase 7 gate E: reports (executive/technical summaries, the
    # insights registry when --insights was used) are part of the SAME
    # reproducibility proof tables/figures already get.
    mismatches |= {
        name: {"original": original.get("reports_written", {}).get(name), "reproduced": h}
        for name, h in reproduced.get("reports_written", {}).items()
        if original.get("reports_written", {}).get(name) != h
    }
    matched = not mismatches

    if as_json:
        print(
            json.dumps(
                {
                    "matched": matched,
                    "mismatches": mismatches,
                    "reproduce_dir": str(resolved_reproduce_dir),
                },
                indent=2,
            )
        )
        return 0 if matched else 1

    print(f"CredLens analysis reproduce: {resolved_output_dir} -> {resolved_reproduce_dir}")
    print("=" * 40)
    if matched:
        n_items = len(reproduced["tables_written"]) + len(reproduced["figures_written"])
        print(f"Result: MATCH ({n_items} table(s)/figure(s), identical content hashes)")
    else:
        print(f"Result: MISMATCH ({len(mismatches)} table(s)/figure(s) differ)")
        for name, diff in mismatches.items():
            print(f"  - {name}: original={diff['original']} reproduced={diff['reproduced']}")
    return 0 if matched else 1


# --- Phase 10: release command handlers -------------------------------------


def _release_error_types() -> tuple[type[Exception], ...]:
    from credlens.release.manifest import ReleaseManifestError

    return (ReleaseManifestError,)


def _cmd_release_validate(as_json: bool) -> int:
    from credlens.release.integrity import run_release_integrity_checks

    report = run_release_integrity_checks()
    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print("CredLens release validate")
        print("=" * 40)
        for check in report.checks:
            print(f"[{check.status.upper()}] {check.name}: {check.detail}")
        print(f"Overall: {report.to_dict()['overall']}")
    return 1 if report.has_failure else 0


def _cmd_release_licenses(as_json: bool) -> int:
    from credlens.release.licenses import inventory_dependency_licenses, write_license_inventory

    inventory = inventory_dependency_licenses()
    path = write_license_inventory(inventory)
    if as_json:
        print(json.dumps(inventory.to_dict(), indent=2))
    else:
        print("CredLens release licenses")
        print("=" * 40)
        print(inventory.disclaimer_en)
        print(f"Project license: {inventory.project_license}")
        print(
            f"{len(inventory.dependencies)} dependencies, {inventory.unknown_count} unknown, "
            f"{inventory.copyleft_count} copyleft"
        )
        for dep in inventory.dependencies:
            if dep.compatibility != "permissive_compatible":
                print(f"  REVIEW: {dep.name} {dep.version} - {dep.license} ({dep.compatibility})")
        print(f"Written to: {path}")
    return 0


def _cmd_release_sbom(as_json: bool) -> int:
    from credlens.release.sbom import generate_sbom, write_sbom

    report = generate_sbom()
    path = write_sbom(report)
    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print("CredLens release sbom")
        print("=" * 40)
        print(f"Components: {report.n_components}")
        print(f"Content fingerprint: {report.content_fingerprint}")
        print(f"Written to: {path}")
    return 0


def _cmd_release_manifest(
    visual_qa_status: str,
    docker_status: str,
    security_scan_status: str,
    ci_status: str,
    test_total: int | None,
    as_json: bool,
) -> int:
    from credlens.release.manifest import build_release_manifest, write_release_manifest

    try:
        manifest = build_release_manifest(
            test_counts={"total": test_total} if test_total is not None else {},
            visual_qa_status=visual_qa_status,
            docker_status=docker_status,
            security_scan_status=security_scan_status,
            ci_status=ci_status,
        )
    except _release_error_types() as exc:
        print(f"Error: {exc}")
        return 1
    path = write_release_manifest(manifest)
    if as_json:
        print(json.dumps(manifest.to_dict(), indent=2))
    else:
        print("CredLens release manifest")
        print("=" * 40)
        print(f"release_id: {manifest.release_id}")
        print(f"readiness_decision: {manifest.readiness_decision}")
        print(f"release_blockers: {manifest.release_blockers}")
        if manifest.release_state == "tagged_release":
            print(f"release_state: tagged_release (HEAD is tag {manifest.nearest_tag})")
        elif manifest.release_state == "unreleased_development":
            print(
                f"release_state: unreleased_development "
                f"({manifest.commits_since_tag} commit(s) past tag {manifest.nearest_tag} - "
                "this release_id/fingerprint do NOT correspond to any published GitHub Release)"
            )
        else:
            print("release_state: no_tags_reachable")
        print(f"Written to: {path}")
    return 0 if manifest.readiness_decision != "release_candidate_not_ready" else 1


def _cmd_release_status(as_json: bool) -> int:
    path = Path("reports/release/release_manifest.json")
    if not path.is_file():
        print("No release manifest found - run 'credlens release manifest' first.")
        return 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print("CredLens release status")
        print("=" * 40)
        print(f"release_id: {payload.get('release_id')}")
        print(f"project_version: {payload.get('project_version')}")
        print(f"readiness_decision: {payload.get('readiness_decision')}")
        print(f"release_blockers: {payload.get('release_blockers')}")
        print(f"release_state: {payload.get('release_state')}")
        print(f"nearest_tag: {payload.get('nearest_tag')}")
        print(f"commits_since_tag: {payload.get('commits_since_tag')}")
        print(f"generated_at_utc: {payload.get('generated_at_utc')}")
    return 0


def _cmd_release_measure_coverage(
    coverage_json: str, test_count: int, pytest_command: str, pytest_exit_code: int, as_json: bool
) -> int:
    from credlens.release.coverage_gate import (
        CoverageGateError,
        build_coverage_snapshot,
        write_coverage_snapshot,
    )

    try:
        snapshot = build_coverage_snapshot(
            Path(coverage_json),
            test_count=test_count,
            command=pytest_command,
            pytest_exit_code=pytest_exit_code,
        )
    except CoverageGateError as exc:
        print(f"Error: {exc}")
        return 1
    path = write_coverage_snapshot(snapshot)
    if as_json:
        print(json.dumps(snapshot.to_dict(), indent=2))
    else:
        print("CredLens release measure-coverage")
        print("=" * 40)
        print(f"coverage_percent: {snapshot.coverage_percent}")
        print(f"total_statements: {snapshot.total_statements}")
        print(f"missing_statements: {snapshot.missing_statements}")
        print(f"test_count: {snapshot.test_count}")
        print(f"pytest_exit_code: {snapshot.pytest_exit_code}")
        print(f"project_version: {snapshot.project_version}")
        print(f"Written to: {path}")
    return 0


def _cmd_release_errata(as_json: bool) -> int:
    from credlens.release.errata import load_release_errata

    entries = load_release_errata()
    if as_json:
        print(json.dumps(entries, indent=2))
        return 0
    print("CredLens release errata")
    print("=" * 40)
    if not entries:
        print("No errata recorded.")
        return 0
    for entry in entries:
        print(f"{entry['errata_id']}: {entry['release_id']}")
        print(f"  {entry['original_decision']} -> {entry['corrected_decision']}")
        print(f"  blockers: {entry['blockers']}")
        print(f"  corrected_at_utc: {entry['corrected_at_utc']}")
    return 0


def _cmd_release_checksums(as_json: bool) -> int:
    from credlens.release.checksums import ChecksumError, write_release_checksums

    try:
        path = write_release_checksums()
    except ChecksumError as exc:
        print(f"Error: {exc}")
        return 1
    if as_json:
        print(json.dumps({"written_to": str(path)}, indent=2))
    else:
        print("CredLens release checksums")
        print("=" * 40)
        print(f"Written to: {path}")
    return 0


def _cmd_release_security(pip_audit_report: Path, trivy_report: Path, as_json: bool) -> int:
    from credlens.release.security import evaluate_security_gate, write_security_audit

    result = evaluate_security_gate(
        pip_audit_report_path=pip_audit_report, trivy_report_path=trivy_report
    )
    path = write_security_audit(result)
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print("CredLens release security")
        print("=" * 40)
        print(f"passed: {result.passed}")
        print(f"pip_audit_report_present: {result.pip_audit_report_present}")
        print(f"trivy_report_present: {result.trivy_report_present}")
        print(f"secret_found_in_image: {result.secret_found_in_image}")
        print(f"blocking_findings: {len(result.blocking_findings)}")
        for finding in result.blocking_findings:
            print(
                f"  [{finding.severity}] {finding.package} {finding.identifier}: {finding.reason}"
            )
        print(f"Written to: {path}")
    return 0 if result.passed else 1


def _dispatch_release_command(args: argparse.Namespace) -> int:
    if args.release_command == "validate":
        return _cmd_release_validate(args.json)
    if args.release_command == "licenses":
        return _cmd_release_licenses(args.json)
    if args.release_command == "sbom":
        return _cmd_release_sbom(args.json)
    if args.release_command == "manifest":
        return _cmd_release_manifest(
            args.visual_qa_status,
            args.docker_status,
            args.security_scan_status,
            args.ci_status,
            args.test_total,
            args.json,
        )
    if args.release_command == "status":
        return _cmd_release_status(args.json)
    if args.release_command == "errata":
        return _cmd_release_errata(args.json)
    if args.release_command == "measure-coverage":
        return _cmd_release_measure_coverage(
            args.coverage_json,
            args.test_count,
            args.pytest_command,
            args.pytest_exit_code,
            args.json,
        )
    if args.release_command == "checksums":
        return _cmd_release_checksums(args.json)
    if args.release_command == "security":
        return _cmd_release_security(args.pip_audit_report, args.trivy_report, args.json)

    print(
        "usage: credlens release {validate,licenses,sbom,manifest,status,errata,"
        "measure-coverage,checksums,security} ..."
    )
    print("Run 'credlens release <command> --help' for details.")
    return 1


# --- main --------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    configure_logging()
    logger.debug("credlens CLI invoked with command=%s version_flag=%s", args.command, args.version)

    if args.version:
        return _cmd_version()
    if args.command == "version":
        return _cmd_version()
    if args.command == "doctor":
        return _cmd_doctor()
    if args.command == "data":
        return _dispatch_data_command(args)
    if args.command == "contracts":
        return _dispatch_contracts_command(args)
    if args.command == "synthetic":
        return _dispatch_synthetic_command(args)
    if args.command == "warehouse":
        return _dispatch_warehouse_command(args)
    if args.command == "analysis":
        return _dispatch_analysis_command(args)
    if args.command == "dashboard":
        return _dispatch_dashboard_command(args)
    if args.command == "demo":
        return _dispatch_demo_command(args)
    if args.command == "model":
        return _dispatch_model_command(args)
    if args.command == "monitor":
        return _dispatch_monitor_command(args)
    if args.command == "release":
        return _dispatch_release_command(args)

    parser.print_help()
    return 0


def _dispatch_warehouse_command(args: argparse.Namespace) -> int:
    if args.warehouse_command == "prepare":
        return _cmd_warehouse_prepare(args.run_id, args.suite_id, args.json)
    if args.warehouse_command == "build":
        return _cmd_warehouse_build(
            args.run_id, args.suite_id, args.build_id, args.force, args.json
        )
    if args.warehouse_command == "test":
        return _cmd_warehouse_test(args.build_id, args.json)
    if args.warehouse_command == "status":
        return _cmd_warehouse_status(args.build_id, args.json)
    if args.warehouse_command == "query":
        return _cmd_warehouse_query(args.build_id, args.name, args.json)
    if args.warehouse_command == "docs":
        return _cmd_warehouse_docs(args.build_id)
    if args.warehouse_command == "reconcile":
        return _cmd_warehouse_reconcile(args.build_id, args.json)

    print("usage: credlens warehouse {prepare,build,test,status,query,docs,reconcile} ...")
    print("Run 'credlens warehouse <command> --help' for details.")
    return 1


def _dispatch_analysis_command(args: argparse.Namespace) -> int:
    if args.analysis_command == "validate":
        return _cmd_analysis_validate(args.build_id, args.json)
    if args.analysis_command == "run":
        return _cmd_analysis_run(
            args.build_id,
            args.output_dir,
            args.force,
            args.no_benchmark,
            args.multiseed,
            args.multiseed_scenario,
            args.multiseed_scale,
            args.multiseed_seeds,
            args.insights,
            args.json,
        )
    if args.analysis_command == "scenarios":
        return _cmd_analysis_scenarios(args.build_id, args.json)
    if args.analysis_command == "benchmark":
        return _cmd_analysis_benchmark(args.json)
    if args.analysis_command == "status":
        return _cmd_analysis_status(args.output_dir, args.analysis_id, args.json)
    if args.analysis_command == "reproduce":
        return _cmd_analysis_reproduce(
            args.output_dir, args.analysis_id, args.reproduce_dir, args.json
        )

    print("usage: credlens analysis {validate,run,scenarios,benchmark,status,reproduce} ...")
    print("Run 'credlens analysis <command> --help' for details.")
    return 1


_DASHBOARD_APP_PATH = Path("dashboard/app.py")
_DEFAULT_DEMO_DATA_DIR = Path("dashboard/demo_data")


def _cmd_dashboard_validate(
    build_id: str | None, demo: bool, demo_data_dir: str | None, as_json: bool
) -> int:
    from credlens.dashboard.config import DashboardConfigError, resolve_config
    from credlens.dashboard.validation import DashboardValidationError, validate_dashboard_source

    try:
        config = resolve_config(
            build_id=build_id,
            demo=demo,
            demo_data_dir=Path(demo_data_dir) if demo_data_dir else None,
        )
        report = validate_dashboard_source(config)
    except (DashboardConfigError, DashboardValidationError) as exc:
        if as_json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"CredLens dashboard validate ({report.mode})")
        print("=" * 40)
        print(f"build_id:    {report.build_id}")
        print(f"fingerprint: {report.fingerprint}")
        print(f"detail:      {report.detail}")
        print("Result: OK (safe to display)")
    return 0


def _cmd_dashboard_export_demo(
    build_id: str,
    analysis_output_dir: str | None,
    output_dir: str | None,
    force: bool,
    as_json: bool,
) -> int:
    from credlens.analysis.validation import AnalysisValidationError, validate_build_for_analysis
    from credlens.dashboard.demo_package import DemoPackageError, build_demo_package

    resolved_output_dir = Path(output_dir) if output_dir else _DEFAULT_DEMO_DATA_DIR
    if (resolved_output_dir / "manifest.json").exists() and not force:
        print(
            f"Error: a demo package already exists at '{resolved_output_dir}'. Pass --force "
            "to overwrite it, or --output-dir to write elsewhere."
        )
        return 1

    resolved_analysis_output_dir = (
        Path(analysis_output_dir) if analysis_output_dir else ANALYSIS_OUTPUT_DIR
    )

    try:
        build = validate_build_for_analysis(build_id)
    except AnalysisValidationError as exc:
        print(f"Error: {exc}")
        return 1

    try:
        manifest = build_demo_package(
            analysis_output_dir=resolved_analysis_output_dir,
            output_dir=resolved_output_dir,
            db_path=Path(build.db_path),
            suite_id=build.suite_id,
        )
    except DemoPackageError as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(manifest.to_dict(), indent=2))
    else:
        print(f"CredLens dashboard export-demo: {resolved_output_dir}")
        print("=" * 40)
        print(f"source build_id:  {manifest.source_build_id}")
        print(f"tables:           {len(manifest.tables)}")
        print(f"insights included: {manifest.insights_included}")
        print(f"total size:       {manifest.total_size_bytes:,} bytes")
    return 0


def _cmd_dashboard_run(
    build_id: str | None, demo: bool, demo_data_dir: str | None, port: int, no_browser: bool
) -> int:
    import subprocess

    from credlens.dashboard.config import DashboardConfigError, resolve_config
    from credlens.dashboard.validation import DashboardValidationError, validate_dashboard_source

    try:
        config = resolve_config(
            build_id=build_id,
            demo=demo,
            demo_data_dir=Path(demo_data_dir) if demo_data_dir else None,
            port=port,
            open_browser=not no_browser,
        )
        report = validate_dashboard_source(config)
    except (DashboardConfigError, DashboardValidationError) as exc:
        print(f"Error: {exc}")
        return 1

    if not _DASHBOARD_APP_PATH.is_file():
        print(f"Error: dashboard entrypoint '{_DASHBOARD_APP_PATH}' was not found.")
        return 1

    print(f"CredLens dashboard: mode={report.mode} build_id={report.build_id} port={port}")
    app_args = ["--demo"] if demo else ["--build-id", str(build_id)]
    if demo_data_dir:
        app_args += ["--demo-data-dir", demo_data_dir]

    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(_DASHBOARD_APP_PATH),
        "--server.port",
        str(port),
        "--server.headless",
        "true" if no_browser else "false",
        "--",
        *app_args,
    ]
    result = subprocess.run(command, check=False)
    return result.returncode


def _cmd_dashboard_status(demo_data_dir: str | None, as_json: bool) -> int:
    from credlens.dashboard.data_access import list_available_builds
    from credlens.dashboard.demo_package import DemoPackageError, load_demo_manifest

    resolved_demo_dir = Path(demo_data_dir) if demo_data_dir else _DEFAULT_DEMO_DATA_DIR
    builds = list_available_builds()
    demo_summary: dict[str, Any] | None = None
    try:
        demo_summary = load_demo_manifest(resolved_demo_dir).to_dict()
    except DemoPackageError:
        demo_summary = None

    payload = {
        "available_builds": builds,
        "demo_package": demo_summary,
        "demo_data_dir": str(resolved_demo_dir),
    }
    if as_json:
        print(json.dumps(payload, indent=2))
        return 0

    print("CredLens dashboard status")
    print("=" * 40)
    print(f"available builds: {builds if builds else '(none)'}")
    if demo_summary:
        print(
            f"demo package:     v{demo_summary['demo_package_version']} from build "
            f"'{demo_summary['source_build_id']}' ({demo_summary['total_size_bytes']:,} bytes)"
        )
    else:
        print(f"demo package:     not found at '{resolved_demo_dir}'")
    return 0


def _cmd_demo_prepare(
    component: str, seed: int, output: str | None, model_id: str | None, force: bool, as_json: bool
) -> int:
    from credlens.demo.factory import (
        DEFAULT_MODEL_ID,
        DemoFactoryError,
        prepare_dashboard_demo,
        prepare_monitoring_demo,
    )

    resolved_output = Path(output) if output else _DEFAULT_DEMO_DATA_DIR
    resolved_model_id = model_id or DEFAULT_MODEL_ID
    results: dict[str, Any] = {}
    try:
        if component in ("dashboard", "all"):
            manifest = prepare_dashboard_demo(
                seed=seed, output_dir=resolved_output, force=force, quiet=as_json
            )
            results["dashboard"] = manifest.to_dict()
        if component in ("monitoring", "all"):
            manifest = prepare_monitoring_demo(
                model_id=resolved_model_id, force=force, quiet=as_json
            )
            results["monitoring"] = manifest.to_dict()
    except DemoFactoryError as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(results, indent=2))
    else:
        print(f"CredLens demo prepare: {component}")
        print("=" * 40)
        for name, manifest_dict in results.items():
            print(f"[{name}] generator_version={manifest_dict['generator_version']}")
            for key, value in manifest_dict["outputs"].items():
                print(f"  {key}: {value}")
    return 0


def _dispatch_demo_command(args: argparse.Namespace) -> int:
    if args.demo_command == "prepare":
        return _cmd_demo_prepare(
            args.component, args.seed, args.output, args.model_id, args.force, args.json
        )

    print("usage: credlens demo {prepare} ...")
    print("Run 'credlens demo <command> --help' for details.")
    return 1


def _dispatch_dashboard_command(args: argparse.Namespace) -> int:
    if args.dashboard_command == "validate":
        return _cmd_dashboard_validate(args.build_id, args.demo, args.demo_data_dir, args.json)
    if args.dashboard_command == "export-demo":
        return _cmd_dashboard_export_demo(
            args.build_id, args.analysis_output_dir, args.output_dir, args.force, args.json
        )
    if args.dashboard_command == "run":
        return _cmd_dashboard_run(
            args.build_id, args.demo, args.demo_data_dir, args.port, args.no_browser
        )
    if args.dashboard_command == "status":
        return _cmd_dashboard_status(args.demo_data_dir, args.json)

    print("usage: credlens dashboard {validate,export-demo,run,status} ...")
    print("Run 'credlens dashboard <command> --help' for details.")
    return 1


def _model_error_types() -> tuple[type[Exception], ...]:
    from credlens.model_validation.evidence import EvidenceError
    from credlens.model_validation.negative_controls import PermutationTestError
    from credlens.model_validation.remediation import RemediationError
    from credlens.model_validation.reporting import ModelValidationError
    from credlens.modeling.contracts import ContractError
    from credlens.modeling.data import DataAcquisitionError
    from credlens.modeling.input_contract import InputContractError
    from credlens.modeling.leakage import LeakageError
    from credlens.modeling.registry import RegistryError
    from credlens.modeling.reporting import ReportingError
    from credlens.modeling.splitting import SplitError

    return (
        ContractError,
        DataAcquisitionError,
        InputContractError,
        LeakageError,
        RegistryError,
        ReportingError,
        SplitError,
        EvidenceError,
        PermutationTestError,
        ModelValidationError,
        RemediationError,
    )


def _monitor_error_types() -> tuple[type[Exception], ...]:
    from credlens.modeling.input_contract import InputContractError
    from credlens.monitoring.batches import BatchBuildError
    from credlens.monitoring.calibration_study import CalibrationStudyError
    from credlens.monitoring.contracts import MonitoringConfigError
    from credlens.monitoring.detection_eval import DetectionEvalError
    from credlens.monitoring.reference import ReferenceError
    from credlens.monitoring.reporting import MonitoringReportingError
    from credlens.monitoring.runner import MonitoringRunError
    from credlens.monitoring.thresholds import ThresholdsError

    return (
        InputContractError,
        BatchBuildError,
        MonitoringConfigError,
        ReferenceError,
        MonitoringReportingError,
        MonitoringRunError,
        CalibrationStudyError,
        DetectionEvalError,
        ThresholdsError,
    )


def _cmd_model_data_audit(as_json: bool) -> int:
    try:
        from credlens.modeling.reporting import data_audit_report

        report = data_audit_report()
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print("CredLens model data-audit (uci-default-credit)")
        print("=" * 40)
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0


def _cmd_model_validate_features(as_json: bool) -> int:
    try:
        from credlens.modeling.reporting import validate_features_report

        report = validate_features_report()
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print("CredLens model validate-features")
        print("=" * 40)
        print(f"feature_registry_version: {report['feature_registry_version']}")
        print(f"feature_count:             {report['feature_count']}")
        print(f"all_finite:                {report['all_finite']}")
        print("Result: OK (static leakage controls passed)")
    return 0


def _cmd_model_create_split(experiment_id: str, seed: int, as_json: bool) -> int:
    try:
        from credlens.modeling.reporting import create_official_split

        assignment = create_official_split(experiment_id, seed=seed)
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    manifest = assignment.manifest.to_dict()
    if as_json:
        print(json.dumps(manifest, indent=2))
    else:
        print(f"CredLens model create-split: {experiment_id}")
        print("=" * 40)
        train_val_test = f"{manifest['n_train']}/{manifest['n_validation']}/{manifest['n_test']}"
        print(f"train/val/test: {train_val_test}")
        print(f"seed:           {manifest['seed']}")
    return 0


def _cmd_model_train(experiment_id: str, seed: int, as_json: bool) -> int:
    try:
        from credlens.modeling.reporting import train_experiment

        experiment = train_experiment(experiment_id, seed=seed)
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(experiment.to_dict(), indent=2))
    else:
        print(f"CredLens model train: {experiment_id}")
        print("=" * 40)
        print(f"status:   {experiment.status}")
        print(f"warnings: {experiment.warnings or '(none)'}")
    return 0


def _cmd_model_evaluate(experiment_id: str, as_json: bool) -> int:
    try:
        from credlens.modeling.reporting import evaluate_experiment

        experiment = evaluate_experiment(experiment_id)
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(experiment.to_dict(), indent=2))
    else:
        main_test = experiment.metrics["test"]["logistic_regression"]
        print(f"CredLens model evaluate: {experiment_id}")
        print("=" * 40)
        print(f"test ROC-AUC: {main_test['discrimination']['roc_auc']}")
        print(f"test PR-AUC:  {main_test['discrimination']['pr_auc']}")
        print(f"test Brier:   {main_test['calibration']['brier_score']}")
    return 0


def _cmd_model_compare(experiment_id: str, as_json: bool) -> int:
    try:
        from credlens.modeling.reporting import compare_models

        table = compare_models(experiment_id)
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(table.to_dict(orient="records"), indent=2))
    else:
        print(f"CredLens model compare: {experiment_id}")
        print("=" * 40)
        print(table.to_string(index=False))
    return 0


def _cmd_model_explain(experiment_id: str, as_json: bool) -> int:
    try:
        from credlens.modeling.reporting import explain_experiment

        explain_experiment(experiment_id)
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    result = {"experiment_id": experiment_id, "status": "explained"}
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"CredLens model explain: {experiment_id}")
        print("=" * 40)
        print("Wrote coefficients/permutation_importance/partial_dependence/local_explanations.")
    return 0


def _cmd_model_audit_groups(experiment_id: str, as_json: bool) -> int:
    try:
        from credlens.modeling.reporting import audit_groups_experiment

        experiment = audit_groups_experiment(experiment_id)
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    summary = experiment.subgroup_audit_summary
    if as_json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"CredLens model audit-groups: {experiment_id}")
        print("=" * 40)
        print(f"max selection-rate gap: {summary.get('max_selection_rate_gap')}")
        print(f"max TPR gap:            {summary.get('max_tpr_gap')}")
        print(f"excluded (insufficient n): {summary.get('excluded_insufficient_groups')}")
        print("Note: not a fairness certification, not a compliance assessment.")
    return 0


def _cmd_model_stress_test(experiment_id: str, as_json: bool) -> int:
    try:
        from credlens.modeling.reporting import stress_test_experiment

        experiment = stress_test_experiment(experiment_id)
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    perturbations = experiment.robustness_summary.get("perturbations", [])
    if as_json:
        print(json.dumps(perturbations, indent=2))
    else:
        print(f"CredLens model stress-test: {experiment_id}")
        print("=" * 40)
        for row in perturbations:
            print(f"{row['kind']}: PR-AUC degradation={row['pr_auc_degradation']}")
    return 0


def _cmd_model_register(experiment_id: str, model_id: str, as_json: bool) -> int:
    try:
        from credlens.modeling.reporting import register_experiment_model

        gate_report, manifest = register_experiment_model(experiment_id, model_id)
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    result = {
        "gate_report": gate_report.to_dict(),
        "model_manifest": manifest.to_dict() if manifest else None,
    }
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"CredLens model register: {experiment_id} -> {model_id}")
        print("=" * 40)
        for gate in gate_report.gates:
            print(f"[{'PASS' if gate.passed else 'FAIL'}] {gate.name}: {gate.detail}")
        print(f"Result: {gate_report.reason}")
    return 0


def _cmd_model_validate(model_id: str, as_json: bool) -> int:
    try:
        from credlens.modeling.registry import validate_model_candidate

        ok = validate_model_candidate(model_id, Path("reports/modeling/models"))
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps({"model_id": model_id, "valid": ok}, indent=2))
    else:
        print(f"CredLens model validate: {model_id}")
        print("=" * 40)
        print(f"Result: {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


def _cmd_model_predict_batch(
    model_id: str, input_path: str, output_path: str | None, as_json: bool
) -> int:
    try:
        from credlens.modeling.features import engineer_features
        from credlens.modeling.interpretability import pseudonymize_id
        from credlens.modeling.registry import load_model_candidate, score_batch

        source = Path(input_path)
        if not source.is_file():
            print(f"Error: input file '{source}' not found.")
            return 1
        raw = pd.read_csv(source)
        if "ID" not in raw.columns:
            print("Error: input CSV must contain an 'ID' column, per the UCI schema.")
            return 1

        pipeline, manifest = load_model_candidate(model_id, Path("reports/modeling/models"))
        features = engineer_features(raw)
        features["pseudonymous_record_id"] = raw["ID"].map(pseudonymize_id)
        scored = score_batch(pipeline, manifest, features)
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if output_path:
        scored.to_csv(output_path, index=False)

    if as_json:
        print(json.dumps(scored.to_dict(orient="records"), indent=2))
    else:
        print(f"CredLens model predict-batch: {model_id}")
        print("=" * 40)
        print(f"rows scored: {len(scored)}")
        if output_path:
            print(f"written to:  {output_path}")
        else:
            print(scored.head(10).to_string(index=False))
    return 0


def _cmd_model_report(
    experiment_id: str, model_id: str | None, no_figures: bool, as_json: bool
) -> int:
    try:
        from credlens.modeling.reporting import generate_figures, write_reports

        written = write_reports(experiment_id, model_id)
        figure_paths: list[Path] = []
        if not no_figures:
            try:
                figure_paths = generate_figures(experiment_id)
            except Exception as exc:  # matplotlib optional - report text still stands
                print(f"Warning: figures not generated ({exc}).")
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    result = {
        "reports_written": {k: str(v) for k, v in written.items()},
        "figures_written": [str(p) for p in figure_paths],
    }
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"CredLens model report: {experiment_id}")
        print("=" * 40)
        for name, path in written.items():
            print(f"{name}: {path}")
        print(f"figures: {len(figure_paths)}")
    return 0


# --- Phase 9: independent validation + challenger CLI handlers --------------


def _cmd_model_validate_independent(model_id: str, ci: bool, as_json: bool) -> int:
    try:
        from credlens.model_validation.reporting import (
            generate_validation_figures,
            validate_independent,
            write_validation_reports,
        )

        result = validate_independent(model_id, full_permutations=not ci)
        write_validation_reports(result.experiment_id)
        try:
            generate_validation_figures(result.experiment_id)
        except Exception as exc:  # matplotlib optional - report text still stands
            print(f"Warning: figures not generated ({exc}).")
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"CredLens model validate-independent: {model_id}")
        print("=" * 40)
        for gate in result.decision.gates:
            print(f"[{gate.status.upper()}] ({gate.severity}) {gate.name}: {gate.result}")
        print(f"Decision: {result.decision.decision}")
        print(f"Reason: {result.decision.reason}")
    return 0 if result.decision.decision != "validation_failed" else 1


def _cmd_model_audit_collinearity(model_id: str, as_json: bool) -> int:
    try:
        from credlens.model_validation.collinearity import run_collinearity_audit
        from credlens.model_validation.evidence import load_validation_config
        from credlens.model_validation.reporting import resolve_experiment_id_from_model
        from credlens.modeling.contracts import (
            load_evaluation_config,
            load_feature_registry,
            load_target_contract,
        )
        from credlens.modeling.data import load_uci_default_credit
        from credlens.modeling.features import engineer_features
        from credlens.modeling.splitting import (
            apply_split_assignment_table,
            load_split_assignment_table,
        )

        experiment_id = resolve_experiment_id_from_model(model_id, Path.cwd())
        contract = load_target_contract()
        df = load_uci_default_credit()
        split_table = load_split_assignment_table(
            Path("reports/modeling/experiments") / experiment_id / "split_assignment.csv"
        )
        assignment = apply_split_assignment_table(
            df, split_table, id_column=contract.identifier_column
        )
        x_train = engineer_features(df).loc[assignment.train_index]
        validation_config = load_validation_config()
        collinearity = run_collinearity_audit(x_train, validation_config.collinearity)
        _ = load_evaluation_config, load_feature_registry
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    result = collinearity.to_dict()
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"CredLens model audit-collinearity: {model_id}")
        print("=" * 40)
        print(f"condition_number: {result['condition_number']}")
        print(f"features_above_action_threshold: {result['features_above_action_threshold']}")
        for pair in result["high_correlation_pairs"][:5]:
            print(f"  {pair['feature_a']} <-> {pair['feature_b']}: {pair['correlation']}")
    return 0


def _cmd_model_audit_negative_controls(experiment_id: str, ci: bool, as_json: bool) -> int:
    try:
        from credlens.model_validation.evidence import load_validation_config
        from credlens.model_validation.negative_controls import (
            run_pipeline_retrain_permutation_control,
            run_score_label_permutation_control,
        )

        cfg = load_validation_config().permutation_test
        c1_cfg = cfg["control1_score_label"]
        c2_cfg = cfg["control2_pipeline_retrain"]
        sigma = float(cfg["centering_sigma_multiplier"])
        n1 = int(c1_cfg["n_permutations_ci"]) if ci else int(c1_cfg["n_permutations_full"])
        n2 = int(c2_cfg["n_permutations_ci"]) if ci else int(c2_cfg["n_permutations_full"])
        control1 = run_score_label_permutation_control(
            experiment_id,
            n_permutations=n1,
            base_seed=int(c1_cfg["base_seed"]),
            alpha=float(c1_cfg["alpha"]),
            centering_sigma_multiplier=sigma,
            amplitude_ratio_min=float(cfg["amplitude_se_ratio_min"]),
            amplitude_ratio_max=float(cfg["amplitude_se_ratio_max"]),
        )
        control2 = run_pipeline_retrain_permutation_control(
            experiment_id,
            n_permutations=n2,
            base_seed=int(c2_cfg["base_seed"]),
            alpha=float(c2_cfg["alpha"]),
            centering_sigma_multiplier=sigma,
        )
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    both_passed = control1.passed and control2.passed
    if as_json:
        print(
            json.dumps(
                {
                    "control1_score_label": control1.to_dict(),
                    "control2_pipeline_retrain": control2.to_dict(),
                },
                indent=2,
            )
        )
    else:
        print(f"CredLens model audit-negative-controls: {experiment_id}")
        print("=" * 40)
        print(
            f"Control 1 (score-label, n={control1.n_permutations}): "
            f"p={control1.empirical_p_value}, {'PASS' if control1.passed else 'FAIL'} - "
            f"{control1.reason}"
        )
        print(
            f"Control 2 (pipeline retrain, n={control2.n_permutations}): "
            f"p={control2.empirical_p_value}, {'PASS' if control2.passed else 'FAIL'} - "
            f"{control2.reason}"
        )
        print(f"Result: {'PASS' if both_passed else 'FAIL'}")
    return 0 if both_passed else 1


def _cmd_model_compare_candidates(experiment_id: str | None, as_json: bool) -> int:
    try:
        from credlens.model_validation.reporting import compare_candidates

        table = compare_candidates(experiment_id)
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(table.to_dict(orient="records"), indent=2))
    else:
        print("CredLens model compare-candidates")
        print("=" * 40)
        print(table.to_string(index=False))
    return 0


def _cmd_model_register_challenger(experiment_id: str, model_id: str | None, as_json: bool) -> int:
    try:
        from credlens.model_validation.reporting import register_challenger_experiment

        manifest = register_challenger_experiment(experiment_id, model_id)
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(manifest.to_dict(), indent=2))
    else:
        print(f"CredLens model register-challenger: {experiment_id} -> {manifest.model_id}")
        print("=" * 40)
        print(f"status: {manifest.status}")
        print(f"artifact_sha256: {manifest.artifact_sha256}")
    return 0


def _cmd_model_remediate(
    model_id: str, new_experiment_id: str, new_model_id: str, as_json: bool
) -> int:
    try:
        from credlens.model_validation.remediation import run_remediation
        from credlens.model_validation.reporting import resolve_experiment_id_from_model

        original_experiment_id = resolve_experiment_id_from_model(model_id, Path.cwd())
        result = run_remediation(original_experiment_id, new_experiment_id, model_id=new_model_id)
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"CredLens model remediate: {model_id} -> {new_experiment_id}")
        print("=" * 40)
        for row in result["comparison"]:
            print(
                f"  {row['model']}: n_features={row['n_features']} pr_auc={row['pr_auc']} "
                f"roc_auc={row['roc_auc']} max_vif={row['max_vif']}"
            )
        print(f"Decision: {result['decision']['decision']}")
        print(f"Reason: {result['decision']['reason']}")
        print(f"Registered model_id: {result['registered_model_id']}")
    return 0 if result["decision"]["decision"] != "remediation_rejected" else 1


def _cmd_model_compare_remediation(new_experiment_id: str, as_json: bool) -> int:
    try:
        from credlens.model_validation.remediation import RemediationError

        table_path = (
            Path("reports/model_validation/tables")
            / f"{new_experiment_id}__remediation_comparison.csv"
        )
        if not table_path.is_file():
            raise RemediationError(
                f"No remediation comparison at '{table_path}' - run 'credlens model remediate' "
                "first."
            )
        table = pd.read_csv(table_path)
    except _model_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(table.to_dict(orient="records"), indent=2))
    else:
        print(f"CredLens model compare-remediation: {new_experiment_id}")
        print("=" * 40)
        print(table.to_string(index=False))
    return 0


def _dispatch_model_command(args: argparse.Namespace) -> int:
    if args.model_command == "data-audit":
        return _cmd_model_data_audit(args.json)
    if args.model_command == "validate-features":
        return _cmd_model_validate_features(args.json)
    if args.model_command == "create-split":
        return _cmd_model_create_split(args.experiment_id, args.seed, args.json)
    if args.model_command == "train":
        return _cmd_model_train(args.experiment_id, args.seed, args.json)
    if args.model_command == "evaluate":
        return _cmd_model_evaluate(args.experiment_id, args.json)
    if args.model_command == "compare":
        return _cmd_model_compare(args.experiment_id, args.json)
    if args.model_command == "explain":
        return _cmd_model_explain(args.experiment_id, args.json)
    if args.model_command == "audit-groups":
        return _cmd_model_audit_groups(args.experiment_id, args.json)
    if args.model_command == "stress-test":
        return _cmd_model_stress_test(args.experiment_id, args.json)
    if args.model_command == "register":
        return _cmd_model_register(args.experiment_id, args.model_id, args.json)
    if args.model_command == "validate":
        return _cmd_model_validate(args.model_id, args.json)
    if args.model_command == "predict-batch":
        return _cmd_model_predict_batch(args.model_id, args.input, args.output, args.json)
    if args.model_command == "report":
        return _cmd_model_report(args.experiment_id, args.model_id, args.no_figures, args.json)
    if args.model_command == "validate-independent":
        return _cmd_model_validate_independent(args.model_id, args.ci, args.json)
    if args.model_command == "audit-collinearity":
        return _cmd_model_audit_collinearity(args.model_id, args.json)
    if args.model_command == "audit-negative-controls":
        return _cmd_model_audit_negative_controls(args.experiment_id, args.ci, args.json)
    if args.model_command == "compare-candidates":
        return _cmd_model_compare_candidates(args.experiment_id, args.json)
    if args.model_command == "register-challenger":
        return _cmd_model_register_challenger(args.experiment_id, args.model_id, args.json)
    if args.model_command == "remediate":
        return _cmd_model_remediate(
            args.model_id, args.new_experiment_id, args.new_model_id, args.json
        )
    if args.model_command == "compare-remediation":
        return _cmd_model_compare_remediation(args.new_experiment_id, args.json)

    print(
        "usage: credlens model {data-audit,validate-features,create-split,train,evaluate,"
        "compare,explain,audit-groups,stress-test,register,validate,predict-batch,report,"
        "validate-independent,audit-collinearity,audit-negative-controls,compare-candidates,"
        "register-challenger,remediate,compare-remediation} ..."
    )
    print("Run 'credlens model <command> --help' for details.")
    return 1


def _cmd_monitor_create_reference(model_id: str, as_json: bool) -> int:
    try:
        from credlens.monitoring.reporting import create_reference

        reference_id = create_reference(model_id)
    except _monitor_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    result = {"reference_id": reference_id}
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"CredLens monitor create-reference: {model_id}")
        print("=" * 40)
        print(f"reference_id: {reference_id}")
    return 0


def _cmd_monitor_calibrate_reference(reference_id: str, as_json: bool) -> int:
    try:
        from credlens.monitoring.reporting import calibrate_reference_family_wise

        result = calibrate_reference_family_wise(reference_id)
    except _monitor_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"CredLens monitor calibrate-reference: {reference_id}")
        print("=" * 40)
        fw = result["psi_family_wise"]
        print(
            f"psi_family_wise: review={fw['review_cutoff']} "
            f"material={fw['material_deviation_cutoff']}"
        )
    return 0


def _cmd_monitor_evaluate_false_alerts(
    reference_id: str, n_batches: int, batch_size: int, as_json: bool
) -> int:
    try:
        from credlens.monitoring.calibration_study import (
            calibrate_family_wise_psi_threshold,
            run_false_alert_rate_study,
        )
        from credlens.monitoring.contracts import load_thresholds_config
        from credlens.monitoring.reference import load_reference, load_reference_population

        thresholds_config = load_thresholds_config()
        mc_cfg = thresholds_config.multiple_comparisons
        reference = load_reference(reference_id)
        reference_population = load_reference_population(reference_id)
        family_wise = calibrate_family_wise_psi_threshold(
            reference_population,
            reference,
            batch_size=batch_size,
            n_resamples=int(mc_cfg["family_wise_n_resamples"]),
            review_percentile=float(mc_cfg["family_wise_review_percentile"]),
            material_percentile=float(mc_cfg["family_wise_material_deviation_percentile"]),
            seed=int(thresholds_config.calibration_study["seed"]),
        )
        study = run_false_alert_rate_study(
            reference_id,
            n_batches=n_batches,
            batch_size=batch_size,
            seed=int(thresholds_config.calibration_study["seed"]),
            family_wise_threshold=family_wise,
        )
        from credlens.release.monitoring_gate import write_false_alert_evidence

        write_false_alert_evidence(study.to_dict())
    except _monitor_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(study.to_dict(), indent=2))
    else:
        print(f"CredLens monitor evaluate-false-alerts: {reference_id}")
        print("=" * 40)
        print(f"n_batches={study.n_batches} batch_size={study.batch_size}")
        print(f"family_wise_marginal_rate (uncorrected): {study.family_wise_marginal_rate}")
        print(f"family_wise_corrected_review_rate: {study.family_wise_corrected_review_rate}")
        print(f"family_wise_corrected_material_rate: {study.family_wise_corrected_material_rate}")
        print(f"score_false_alert_rate: {study.score_false_alert_rate}")
        print(f"performance_false_alert_rate: {study.performance_false_alert_rate}")
        print(f"combined_material_false_alert_rate: {study.combined_material_false_alert_rate}")
        print(f"high_severity_false_alert_rate: {study.high_severity_false_alert_rate}")
    return 0


def _cmd_monitor_evaluate_detection(reference_id: str, as_json: bool) -> int:
    try:
        from credlens.monitoring.detection_eval import run_detection_evaluation
        from credlens.release.monitoring_gate import write_detection_evidence

        report = run_detection_evaluation(reference_id)
        write_detection_evidence(report.to_dict())
    except _monitor_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"CredLens monitor evaluate-detection: {reference_id}")
        print("=" * 40)
        for row in report.rows:
            print(
                f"  {row.scenario}: expected={row.expected_category} detected={row.detected} "
                f"severity={row.detected_severity} correctly_blocked={row.correctly_blocked}"
            )
        print(f"scenario_detection_rate: {report.scenario_detection_rate}")
        print(f"blocked_input_recall: {report.blocked_input_recall}")
        print(f"severity_precision: {report.severity_precision}")
        print(f"alert_compression_ratio: {report.incident_report.alert_compression_ratio}")
        print(f"incident_compression_ratio: {report.incident_report.incident_compression_ratio}")
    return 0


def _cmd_monitor_simulate_batches(reference_id: str, as_json: bool) -> int:
    try:
        from credlens.monitoring.reporting import simulate_batches

        batch_set_id = simulate_batches(reference_id)
    except _monitor_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    result = {"batch_set_id": batch_set_id}
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"CredLens monitor simulate-batches: {reference_id}")
        print("=" * 40)
        print(f"batch_set_id: {batch_set_id}")
    return 0


def _cmd_monitor_run(reference_id: str, batch_set: str, as_json: bool) -> int:
    try:
        from credlens.monitoring.reporting import run as run_monitoring_pipeline

        run_id = run_monitoring_pipeline(reference_id, batch_set)
    except _monitor_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    result = {"run_id": run_id}
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"CredLens monitor run: {reference_id} / {batch_set}")
        print("=" * 40)
        print(f"run_id: {run_id}")
    return 0


def _cmd_monitor_status(run_id: str, as_json: bool) -> int:
    try:
        from credlens.monitoring.reporting import status as monitor_status

        record = monitor_status(run_id)
    except _monitor_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(record, indent=2))
    else:
        print(f"CredLens monitor status: {run_id}")
        print("=" * 40)
        print(f"n_batches: {record['n_batches']}")
        print(f"n_alerts: {record['n_alerts']}")
        for batch in record["batches"]:
            print(
                f"  batch {batch['batch_sequence']:02d} ({batch['simulation_scenario']}): "
                f"{'BLOCKED' if batch['blocked'] else 'scored'}"
            )
    return 0


def _cmd_monitor_alerts(run_id: str, as_json: bool) -> int:
    try:
        from credlens.monitoring.alerts import load_alerts

        alerts = load_alerts(run_id)
    except _monitor_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps(alerts, indent=2))
    else:
        print(f"CredLens monitor alerts: {run_id}")
        print("=" * 40)
        if not alerts:
            print("(no alerts)")
        for alert in alerts:
            print(
                f"[{alert['severity']}] {alert['alert_id']} - "
                f"{alert['category']}/{alert['metric']}: {alert['status']}"
            )
    return 0


def _cmd_monitor_report(run_id: str, as_json: bool) -> int:
    try:
        from credlens.monitoring.reporting import write_monitoring_reports

        written = write_monitoring_reports(run_id)
    except _monitor_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    result = {k: str(v) for k, v in written.items()}
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"CredLens monitor report: {run_id}")
        print("=" * 40)
        for name, path in written.items():
            print(f"{name}: {path}")
    return 0


def _cmd_monitor_validate(run_id: str, as_json: bool) -> int:
    try:
        from credlens.monitoring.reporting import validate_run

        ok = validate_run(run_id)
    except _monitor_error_types() as exc:
        print(f"Error: {exc}")
        return 1

    if as_json:
        print(json.dumps({"run_id": run_id, "valid": ok}, indent=2))
    else:
        print(f"CredLens monitor validate: {run_id}")
        print("=" * 40)
        print(f"Result: {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


def _dispatch_monitor_command(args: argparse.Namespace) -> int:
    if args.monitor_command == "create-reference":
        return _cmd_monitor_create_reference(args.model_id, args.json)
    if args.monitor_command == "simulate-batches":
        return _cmd_monitor_simulate_batches(args.reference_id, args.json)
    if args.monitor_command == "run":
        return _cmd_monitor_run(args.reference_id, args.batch_set, args.json)
    if args.monitor_command == "status":
        return _cmd_monitor_status(args.run_id, args.json)
    if args.monitor_command == "alerts":
        return _cmd_monitor_alerts(args.run_id, args.json)
    if args.monitor_command == "report":
        return _cmd_monitor_report(args.run_id, args.json)
    if args.monitor_command == "validate":
        return _cmd_monitor_validate(args.run_id, args.json)
    if args.monitor_command == "calibrate-reference":
        return _cmd_monitor_calibrate_reference(args.reference_id, args.json)
    if args.monitor_command == "evaluate-false-alerts":
        return _cmd_monitor_evaluate_false_alerts(
            args.reference_id, args.n_batches, args.batch_size, args.json
        )
    if args.monitor_command == "evaluate-detection":
        return _cmd_monitor_evaluate_detection(args.reference_id, args.json)

    print(
        "usage: credlens monitor {create-reference,calibrate-reference,simulate-batches,run,"
        "status,alerts,report,validate,evaluate-false-alerts,evaluate-detection} ..."
    )
    print("Run 'credlens monitor <command> --help' for details.")
    return 1


def _dispatch_contracts_command(args: argparse.Namespace) -> int:
    if args.contracts_command == "list":
        return _cmd_contracts_list()
    if args.contracts_command == "show":
        return _cmd_contracts_show(args.name)
    if args.contracts_command == "validate":
        return _cmd_contracts_validate(args.contract, args.path, args.mode)

    print("usage: credlens contracts {list,show,validate} ...")
    print("Run 'credlens contracts <command> --help' for details.")
    return 1


def _dispatch_synthetic_command(args: argparse.Namespace) -> int:
    if args.synthetic_command == "plan":
        return _cmd_synthetic_plan()
    if args.synthetic_command == "scenarios":
        return _cmd_synthetic_scenarios()
    if args.synthetic_command == "validate-blueprints":
        return _cmd_synthetic_validate_blueprints()
    if args.synthetic_command == "generate":
        return _cmd_synthetic_generate(args.scenario, args.scale, args.seed, args.force)
    if args.synthetic_command == "validate":
        return _cmd_synthetic_validate_run(args.run_id)
    if args.synthetic_command == "inspect":
        return _cmd_synthetic_inspect(args.run_id)
    if args.synthetic_command == "manifest":
        return _cmd_synthetic_manifest(args.run_id)
    if args.synthetic_command == "generate-suite":
        return _cmd_synthetic_generate_suite(args.scale, args.seed, args.force)
    if args.synthetic_command == "compare":
        return _cmd_synthetic_compare(args.baseline, args.candidate)
    if args.synthetic_command == "validate-suite":
        return _cmd_synthetic_validate_suite(args.suite_id)
    if args.synthetic_command == "monte-carlo":
        return _cmd_synthetic_monte_carlo(args.scenario, args.scale, args.seeds, args.start_seed)
    if args.synthetic_command == "profile":
        return _cmd_synthetic_profile(args.scenario, args.scale, args.seed)

    print(
        "usage: credlens synthetic {plan,scenarios,validate-blueprints,generate,validate,"
        "inspect,manifest,generate-suite,compare,validate-suite,monte-carlo,profile} ..."
    )
    print("Run 'credlens synthetic <command> --help' for details.")
    return 1


def _dispatch_data_command(args: argparse.Namespace) -> int:
    if args.data_command == "sources":
        return _cmd_data_sources()
    if args.data_command == "fetch":
        return _cmd_data_fetch(args.source, args.force, args.start, args.end)
    if args.data_command == "verify":
        return _cmd_data_verify(args.source)
    if args.data_command == "audit":
        return _cmd_data_audit(args.source)

    print("usage: credlens data {sources,fetch,verify,audit} ...")
    print("Run 'credlens data <command> --help' for details.")
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
