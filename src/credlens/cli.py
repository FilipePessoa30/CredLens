"""CredLens command-line interface.

Foundation phase: verifies the installation and the project scaffolding.
Phase 2 adds data acquisition/provenance/audit commands (`credlens data
...`). Neither phase touches models, dashboards, or business KPIs - see
docs/roadmap.md.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

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
        help="Synthetic-generation planning commands (Phase 3: design only, no generation).",
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
    synthetic_subparsers.add_parser(
        "generate", help="Not implemented in this phase - reports that clearly and exits."
    )

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
    print("credlens synthetic generate: Not implemented: scheduled for the synthetic")
    print("generation phase. See docs/synthetic_generation_spec.md and docs/roadmap.md.")
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


def _cmd_synthetic_generate() -> int:
    print("Not implemented: scheduled for the synthetic generation phase.")
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

    parser.print_help()
    return 0


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
        return _cmd_synthetic_generate()

    print("usage: credlens synthetic {plan,scenarios,validate-blueprints,generate} ...")
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
