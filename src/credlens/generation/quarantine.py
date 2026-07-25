"""Data-quality-incident injection and quarantine (Phase 4B, section 10).

Never mixes a deliberately-broken table set with a valid run: a real,
already-validated run is copied into memory first, exactly ONE controlled
defect is injected, strict contract validation is run and MUST fail (an
incident whose injection does NOT produce the expected error is itself an
error - see IncidentError), and only then is the result written to
data/quarantine/<incident_run_id>/ with generation_runs.status =
'quarantined_expected_failure'. A quarantined run is NEVER written to
data/synthetic/, NEVER marked 'completed', and NEVER read by
credlens synthetic validate/inspect/manifest (those only resolve run ids
under config.output.operational_dir, which quarantine is deliberately
outside of).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from credlens.contracts.models import DataContract
from credlens.contracts.registry import load_all_contracts
from credlens.generation.validation import validate_contracts_strict
from credlens.generation.writers import write_operational_tables

Tables = dict[str, pd.DataFrame]


class IncidentError(Exception):
    """Raised when an incident's own expectation isn't met - e.g. the injected
    defect did NOT actually fail strict contract validation, which would mean the
    incident doesn't test what it claims to."""


@dataclass(frozen=True)
class IncidentDefinition:
    incident_id: str
    description: str
    expected_error_code: str
    expected_contract: str
    inject: Callable[[Tables], Tables]


@dataclass(frozen=True)
class IncidentOutcome:
    incident_id: str
    quarantine_run_id: str
    quarantine_dir: Path
    expected_error_code: str
    found_expected_error: bool
    error_codes_found: dict[str, list[str]]


def _copy_tables(tables: Tables) -> Tables:
    return {name: df.copy(deep=True) for name, df in tables.items()}


def _inject_duplicate_primary_key(tables: Tables) -> Tables:
    tables = _copy_tables(tables)
    customers = tables["customers"]
    if len(customers) < 2:
        raise IncidentError("duplicate_primary_key needs at least 2 customers rows.")
    duplicated_row = customers.iloc[[0]].copy()
    duplicated_row["customer_id"] = customers.iloc[1]["customer_id"]
    tables["customers"] = pd.concat([customers, duplicated_row], ignore_index=True)
    return tables


def _inject_orphan_foreign_key(tables: Tables) -> Tables:
    tables = _copy_tables(tables)
    applications = tables["applications"]
    if applications.empty:
        raise IncidentError("orphan_foreign_key needs at least 1 applications row.")
    applications = applications.copy()
    applications.loc[applications.index[0], "customer_id"] = "CUS_NONEXISTENT_9999999"
    tables["applications"] = applications
    return tables


def _inject_invalid_domain(tables: Tables) -> Tables:
    tables = _copy_tables(tables)
    decisions = tables["credit_decisions"]
    if decisions.empty:
        raise IncidentError("invalid_domain needs at least 1 credit_decisions row.")
    decisions = decisions.copy()
    decisions.loc[decisions.index[0], "outcome"] = "maybe_later"
    tables["credit_decisions"] = decisions
    return tables


def _inject_incoherent_snapshot(tables: Tables) -> Tables:
    """Duplicates a terminal-status contract's own last snapshot one month later -
    violates no_snapshot_after_terminal_status."""
    tables = _copy_tables(tables)
    snapshots = tables["account_monthly_snapshots"]
    terminal = snapshots[snapshots["status"].isin(["settled", "closed", "charged_off"])]
    if terminal.empty:
        raise IncidentError(
            "incoherent_snapshot needs at least 1 terminal-status snapshot row - "
            "regenerate the source run with a scenario/scale that produces one "
            "(e.g. contract_coverage)."
        )
    stale_row = terminal.iloc[[0]].copy()
    stale_date = pd.Timestamp(stale_row.iloc[0]["snapshot_date"]) + pd.DateOffset(months=1)
    stale_row["snapshot_date"] = stale_date.strftime("%Y-%m-%d")
    tables["account_monthly_snapshots"] = pd.concat([snapshots, stale_row], ignore_index=True)
    return tables


def _inject_impossible_date(tables: Tables) -> Tables:
    tables = _copy_tables(tables)
    decisions = tables["credit_decisions"]
    applications = tables["applications"]
    if decisions.empty:
        raise IncidentError("impossible_date needs at least 1 credit_decisions row.")
    decisions = decisions.copy()
    application_id = decisions.iloc[0]["application_id"]
    submitted_at = applications.loc[
        applications["application_id"] == application_id, "submitted_at"
    ].iloc[0]
    impossible_ts = pd.Timestamp(submitted_at) - pd.Timedelta(days=30)
    decisions.loc[decisions.index[0], "decision_timestamp"] = impossible_ts.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    tables["credit_decisions"] = decisions
    return tables


INCIDENTS: dict[str, IncidentDefinition] = {
    "duplicate_primary_key": IncidentDefinition(
        incident_id="duplicate_primary_key",
        description="A customers row's customer_id is duplicated onto a second row.",
        expected_error_code="PK_DUPLICATE",
        expected_contract="customers",
        inject=_inject_duplicate_primary_key,
    ),
    "orphan_foreign_key": IncidentDefinition(
        incident_id="orphan_foreign_key",
        description="An applications row's customer_id references a customer that doesn't exist.",
        expected_error_code="FK_ORPHAN",
        expected_contract="applications",
        inject=_inject_orphan_foreign_key,
    ),
    "invalid_domain": IncidentDefinition(
        incident_id="invalid_domain",
        description="A credit_decisions row's outcome is set outside its declared domain.",
        expected_error_code="DOMAIN_VIOLATION",
        expected_contract="credit_decisions",
        inject=_inject_invalid_domain,
    ),
    "incoherent_snapshot": IncidentDefinition(
        incident_id="incoherent_snapshot",
        description=(
            "A terminal-status contract's last snapshot is duplicated one month "
            "later - a snapshot exists after the contract already closed."
        ),
        expected_error_code="SNAPSHOT_AFTER_TERMINAL_STATUS",
        expected_contract="account_monthly_snapshots",
        inject=_inject_incoherent_snapshot,
    ),
    "impossible_date": IncidentDefinition(
        incident_id="impossible_date",
        description="A credit_decisions row's decision_timestamp precedes its own submitted_at.",
        expected_error_code="DECISION_BEFORE_SUBMISSION",
        expected_contract="credit_decisions",
        inject=_inject_impossible_date,
    ),
}


def _read_operational_tables(operational_dir: Path) -> Tables:
    tables: Tables = {}
    for path in sorted(operational_dir.glob("*.parquet")):
        tables[path.stem] = pd.read_parquet(path)
    return tables


def run_incident(
    source_operational_dir: Path,
    incident_id: str,
    quarantine_base_dir: Path,
    source_run_id: str,
) -> IncidentOutcome:
    """Loads an already-generated, already-valid run's operational tables,
    injects exactly one controlled defect, confirms it fails strict contract
    validation as expected, and writes the broken copy (plus a
    quarantine_manifest.json) under quarantine_base_dir/<quarantine_run_id>/ -
    never under data/synthetic/. Raises IncidentError if the injected defect
    does not actually produce the expected error (the incident would not be
    testing what it claims to)."""
    if incident_id not in INCIDENTS:
        raise IncidentError(
            f"Unknown incident '{incident_id}'. Known incidents: {sorted(INCIDENTS)}"
        )
    incident = INCIDENTS[incident_id]

    valid_tables = _read_operational_tables(source_operational_dir)
    broken_tables = incident.inject(valid_tables)

    all_contracts: dict[str, DataContract] = load_all_contracts()
    reports = validate_contracts_strict(broken_tables, all_contracts)

    error_codes_found: dict[str, list[str]] = {}
    for name, report in reports.items():
        codes = sorted({f.code for f in report.findings if f.severity == "error"})
        if codes:
            error_codes_found[name] = codes

    found_expected = incident.expected_error_code in error_codes_found.get(
        incident.expected_contract, []
    )
    if not found_expected:
        raise IncidentError(
            f"Incident '{incident_id}' was expected to produce error code "
            f"'{incident.expected_error_code}' on contract '{incident.expected_contract}' "
            f"but strict validation found: {error_codes_found}. The injected defect did not "
            "produce the failure this incident claims to test."
        )

    quarantine_run_id = f"QUARANTINE_{incident_id}_{source_run_id}"
    quarantine_dir = quarantine_base_dir / quarantine_run_id
    if quarantine_dir.exists():
        import shutil

        shutil.rmtree(quarantine_dir)
    operational_dir = quarantine_dir / "operational"

    if "generation_runs" in broken_tables:
        broken_tables["generation_runs"] = broken_tables["generation_runs"].copy()
        broken_tables["generation_runs"]["status"] = "quarantined_expected_failure"

    write_operational_tables(broken_tables, operational_dir)

    manifest = {
        "quarantine_run_id": quarantine_run_id,
        "source_run_id": source_run_id,
        "incident_id": incident_id,
        "description": incident.description,
        "expected_error_code": incident.expected_error_code,
        "expected_contract": incident.expected_contract,
        "found_expected_error": found_expected,
        "error_codes_found": error_codes_found,
        "status": "quarantined_expected_failure",
    }
    (quarantine_dir / "quarantine_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )

    return IncidentOutcome(
        incident_id=incident_id,
        quarantine_run_id=quarantine_run_id,
        quarantine_dir=quarantine_dir,
        expected_error_code=incident.expected_error_code,
        found_expected_error=found_expected,
        error_codes_found=error_codes_found,
    )
