"""Tests for credlens.contracts.validators: orchestration of domain +
business-rule checks into a ValidationReport, and audit/strict dispatch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from credlens.contracts.loader import load_contract
from credlens.contracts.registry import load_all_contracts
from credlens.contracts.validators import (
    ValidationRunError,
    load_scenario_tables,
    read_table,
    validate,
)

APPLICATIONS_CONTRACT = load_contract(Path("contracts/operational/applications.yaml"))
BCB_CONTRACT = load_contract(Path("contracts/raw/bcb_sgs_20570.yaml"))


class TestReadTable:
    def test_reads_csv(self, tmp_path: Path) -> None:
        path = tmp_path / "applications.csv"
        path.write_text("application_id\napp-1\n", encoding="utf-8")

        df = read_table(path, APPLICATIONS_CONTRACT)

        assert list(df["application_id"]) == ["app-1"]

    def test_reads_json(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        path.write_text(json.dumps([{"data": "01/01/2020", "valor": "1"}]), encoding="utf-8")

        df = read_table(path, BCB_CONTRACT)

        assert list(df["data"]) == ["01/01/2020"]

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationRunError):
            read_table(tmp_path / "missing.csv", APPLICATIONS_CONTRACT)


class TestLoadScenarioTables:
    def test_loads_only_contracts_with_a_matching_file(self, tmp_path: Path) -> None:
        (tmp_path / "applications.csv").write_text("application_id\napp-1\n", encoding="utf-8")
        contracts = {"applications": APPLICATIONS_CONTRACT}

        tables = load_scenario_tables(tmp_path, contracts)

        assert set(tables) == {"applications"}

    def test_contract_without_matching_file_is_simply_absent(self, tmp_path: Path) -> None:
        contracts = {"applications": APPLICATIONS_CONTRACT}

        tables = load_scenario_tables(tmp_path, contracts)

        assert tables == {}


class TestValidate:
    def test_unknown_mode_raises_value_error(self, tmp_path: Path) -> None:
        path = tmp_path / "applications.csv"
        path.write_text("application_id\napp-1\n", encoding="utf-8")

        with pytest.raises(ValueError, match="Unknown validation mode"):
            validate(APPLICATIONS_CONTRACT, path, mode="not_a_mode")

    def test_missing_path_raises_validation_run_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationRunError, match=r"not found|Path not found"):
            validate(APPLICATIONS_CONTRACT, tmp_path / "missing.csv", mode="audit")

    def test_directory_without_all_contracts_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationRunError, match="full contract registry"):
            validate(APPLICATIONS_CONTRACT, tmp_path, mode="audit")

    def test_directory_missing_contract_file_raises(self, tmp_path: Path) -> None:
        contracts = load_all_contracts()
        with pytest.raises(ValidationRunError, match="No file for contract"):
            validate(APPLICATIONS_CONTRACT, tmp_path, mode="audit", all_contracts=contracts)

    def test_single_file_validation_runs_domain_checks(self, tmp_path: Path) -> None:
        path = tmp_path / "applications.csv"
        path.write_text(
            "application_id,customer_id,generation_run_id,submitted_at,product,channel,"
            "requested_amount,requested_term_months,status\n"
            "app-1,cust-1,run-1,2024-01-01T00:00:00Z,personal_loan,web,1000,12,submitted\n",
            encoding="utf-8",
        )

        report = validate(APPLICATIONS_CONTRACT, path, mode="audit")

        assert report.contract == "applications"
        assert report.mode == "audit"
        assert report.row_count == 1
        # FK checks against customers/generation_runs can't run (not supplied) -> info findings only
        assert not report.has_errors

    def test_single_file_business_rule_needing_other_table_reports_info(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "applications.csv"
        path.write_text(
            "application_id,customer_id,generation_run_id,submitted_at,product,channel,"
            "requested_amount,requested_term_months,status\n"
            "app-1,cust-1,run-1,2024-01-01T00:00:00Z,personal_loan,web,1000,12,submitted\n",
            encoding="utf-8",
        )

        report = validate(APPLICATIONS_CONTRACT, path, mode="audit")
        codes = {f.code for f in report.findings}

        assert (
            "RULE_NOT_EVALUATED" in codes
        )  # decision_not_before_submission needs credit_decisions

    def test_audit_mode_never_forces_failure_via_report_has_errors_alone(
        self, tmp_path: Path
    ) -> None:
        """audit mode still *reports* errors truthfully - the CLI is what
        decides not to fail the process on them (see cli.py). This test
        only asserts the report captures a real error when one exists."""
        path = tmp_path / "applications.csv"
        path.write_text(
            "application_id,customer_id,generation_run_id,submitted_at,product,channel,"
            "requested_amount,requested_term_months,status\n"
            "app-1,cust-1,run-1,2024-01-01T00:00:00Z,personal_loan,carrier_pigeon,1000,12,submitted\n",
            encoding="utf-8",
        )

        report = validate(APPLICATIONS_CONTRACT, path, mode="audit")

        assert report.has_errors is True

    def test_directory_validation_runs_cross_table_business_rules(self, tmp_path: Path) -> None:
        contracts = load_all_contracts()
        (tmp_path / "applications.csv").write_text(
            "application_id,customer_id,generation_run_id,submitted_at,product,channel,"
            "requested_amount,requested_term_months,status\n"
            "app-1,cust-1,run-1,2024-01-10T00:00:00Z,personal_loan,web,1000,12,submitted\n",
            encoding="utf-8",
        )
        (tmp_path / "credit_decisions.csv").write_text(
            "decision_id,application_id,policy_version_id,decision_timestamp,outcome,reason_code,"
            "approved_amount,approved_term_months,offered_rate,is_final,logic_version\n"
            "dec-1,app-1,pv-1,2024-01-05T00:00:00Z,rejected,score_too_low,,,,"
            "true,v1\n",
            encoding="utf-8",
        )

        report = validate(
            contracts["credit_decisions"], tmp_path, mode="strict", all_contracts=contracts
        )
        codes = {f.code for f in report.findings}

        assert "DECISION_BEFORE_SUBMISSION" in codes
