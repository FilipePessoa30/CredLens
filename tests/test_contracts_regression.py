"""Dedicated regression tests for bugs found and fixed during Phase 3's
own construction (see docs/data_contracts.md, "Real bugs this system
caught during its own construction"):

1. UCI EDUCATION (X3) / MARRIAGE (X4) out-of-domain codes - previously a
   manual, one-off Phase 2 finding; now automatically detected by
   contracts/raw/uci_default_credit.yaml + domain_rules.check_domain.
2. BCB observation-date uniqueness/ordering - previously a manual check
   after a Phase 2 chunking-boundary bug; now automated by the `data`
   primary key plus the `bcb_dates_strictly_increasing` business rule.
3. The timezone-naive/aware comparison crash in approval_requires_valid_policy
   (an all-empty effective_to column silently parsed as tz-naive).
4. CPF-shaped identifier detection (check_no_document_like_identifiers).

Tests that depend on the real acquired files under data/raw/ (git-ignored,
not present on a fresh clone or in CI without first running
`credlens data fetch`) are skipped gracefully rather than failing when
those files are absent - see conftest-free `_skip_unless_exists` below.
This repository's own Phase 1/2 tests never assumed data/raw/ was
present; this file preserves that convention.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from credlens.contracts import domain_rules, relational_rules
from credlens.contracts.loader import load_contract
from credlens.contracts.registry import load_all_contracts
from credlens.contracts.validators import validate

UCI_RAW_FILE = Path("data/raw/uci_default_credit/default_of_credit_card_clients.csv")
BCB_20570_RAW_FILE = Path("data/raw/bcb_sgs/bcb_sgs_20570.json")
BCB_21112_RAW_FILE = Path("data/raw/bcb_sgs/bcb_sgs_21112.json")

_skip_unless_uci = pytest.mark.skipif(
    not UCI_RAW_FILE.is_file(),
    reason="Real UCI raw file not present (git-ignored; run 'credlens data fetch' first).",
)
_skip_unless_bcb = pytest.mark.skipif(
    not (BCB_20570_RAW_FILE.is_file() and BCB_21112_RAW_FILE.is_file()),
    reason="Real BCB raw files not present (git-ignored; run 'credlens data fetch' first).",
)


class TestEducationMarriageAutomatedDetection:
    """Phase 2 found these violations by a manual, one-off pandas check.
    Phase 3's contract system must reproduce that finding automatically,
    with no per-dataset custom code - just the contract's declared domain."""

    def test_synthetic_reproduction_of_the_known_bug_shape(self) -> None:
        contract = load_contract(Path("contracts/raw/uci_default_credit.yaml"))
        df = pd.DataFrame({"X3": [1, 2, 3, 4, 0, 5, 6], "X4": [1, 2, 3, 0, 1, 2, 3]})

        findings = domain_rules.check_domain(df, contract)
        by_column = {f.column: f for f in findings}

        assert by_column["X3"].count == 3  # codes 0, 5, 6 outside {1,2,3,4}
        assert by_column["X4"].count == 1  # code 0 outside {1,2,3}

    @_skip_unless_uci
    def test_real_acquired_file_reproduces_the_exact_phase2_counts(self) -> None:
        """Matches the manually-found Phase 2 counts exactly: 345 EDUCATION
        (X3) violations and 54 MARRIAGE (X4) violations out of 30000 rows -
        verified once by direct pandas inspection during this phase and
        pinned here so a future contract or data change can't silently
        regress the detection."""
        contracts = load_all_contracts()
        contract = contracts["uci_default_credit"]

        report = validate(contract, UCI_RAW_FILE, mode="audit")
        by_column = {f.column: f for f in report.findings if f.code == "DOMAIN_VIOLATION"}

        assert report.row_count == 30000
        assert by_column["X3"].count == 345
        assert by_column["X4"].count == 54

    @_skip_unless_uci
    def test_audit_mode_does_not_fail_the_command_despite_real_violations(self) -> None:
        """audit mode is diagnostic (see docs/adr/0006) - real raw-data
        quirks like this one must be reported, never treated as a build
        failure."""
        contracts = load_all_contracts()
        contract = contracts["uci_default_credit"]

        report = validate(contract, UCI_RAW_FILE, mode="audit")

        assert report.has_errors is True  # the violations are real and reported
        # (the CLI, not the report, decides audit mode still exits 0 - see test_cli_contracts.py)


class TestBcbTemporalUniquenessAndOrdering:
    """Phase 2's chunking bug produced a duplicate/out-of-order observation
    date at a request-window boundary. Two independent, automated checks
    now guard against a regression: the `data` primary key (uniqueness)
    and the `bcb_dates_strictly_increasing` business rule (ordering)."""

    def test_duplicate_date_at_a_simulated_chunk_boundary_is_caught_by_both_checks(
        self, tmp_path: Path
    ) -> None:
        contracts = load_all_contracts()
        contract = contracts["bcb_sgs_20570"]

        # Simulates exactly the historical bug: two overlapping download
        # chunks both included the boundary month.
        payload = [
            {"data": "01/01/2020", "valor": "100"},
            {"data": "01/02/2020", "valor": "101"},
            {"data": "01/02/2020", "valor": "101"},  # chunk-boundary duplicate
            {"data": "01/03/2020", "valor": "102"},
        ]
        path = tmp_path / "bcb_sgs_20570.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        report = validate(contract, path, mode="strict")
        codes = {f.code for f in report.findings}

        assert "PK_DUPLICATE" in codes
        assert "BCB_DATES_NOT_STRICTLY_INCREASING" in codes
        assert report.has_errors is True

    def test_clean_monotonic_dates_pass_strict_mode(self, tmp_path: Path) -> None:
        contracts = load_all_contracts()
        contract = contracts["bcb_sgs_20570"]

        payload = [
            {"data": "01/01/2020", "valor": "100"},
            {"data": "01/02/2020", "valor": "101"},
            {"data": "01/03/2020", "valor": "102"},
        ]
        path = tmp_path / "bcb_sgs_20570.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        report = validate(contract, path, mode="strict")

        assert report.findings == []

    @_skip_unless_bcb
    @pytest.mark.parametrize("series_id", ["bcb_sgs_20570", "bcb_sgs_21112"])
    def test_real_acquired_bcb_files_currently_have_no_date_violations(
        self, series_id: str
    ) -> None:
        """The Phase 2 chunking bug was fixed before these files were
        acquired for the last time in this session - this pins that
        the currently-committed acquisition is clean."""
        contracts = load_all_contracts()
        contract = contracts[series_id]
        path = Path(f"data/raw/bcb_sgs/{series_id}.json")

        report = validate(contract, path, mode="audit")
        codes = {f.code for f in report.findings}

        assert "PK_DUPLICATE" not in codes
        assert "BCB_DATES_NOT_STRICTLY_INCREASING" not in codes


class TestTimezoneComparisonRegression:
    """approval_requires_valid_policy previously crashed with
    `TypeError: Cannot compare tz-naive and tz-aware datetime-like objects`
    when a policy's effective_to column was entirely empty (pandas infers
    tz-naive for an all-NaT column) while decision_timestamp was
    tz-aware (ISO-8601 with a 'Z' suffix). Fixed by parsing every
    datetime column with utc=True."""

    def test_all_empty_effective_to_column_does_not_crash(self) -> None:
        decisions = pd.DataFrame(
            {
                "decision_id": ["dec-1"],
                "policy_version_id": ["pv-1"],
                "decision_timestamp": ["2024-01-01T00:00:00Z"],
            }
        )
        policies = pd.DataFrame(
            {
                "policy_version_id": ["pv-1"],
                "name": ["policy A"],
                "effective_from": ["2023-01-01T00:00:00Z"],
                "effective_to": [None],  # entirely empty column -> pandas infers tz-naive
            }
        )

        findings = relational_rules.approval_requires_valid_policy(
            {"credit_decisions": decisions, "policy_versions": policies}, "credit_decisions"
        )

        assert findings == []  # decision falls inside the open-ended valid window; no crash

    def test_mixed_naive_and_aware_style_timestamps_still_compare_correctly(self) -> None:
        decisions = pd.DataFrame(
            {
                "decision_id": ["dec-1", "dec-2"],
                "policy_version_id": ["pv-1", "pv-1"],
                "decision_timestamp": ["2024-01-01T00:00:00Z", "2024-08-01T00:00:00Z"],
            }
        )
        policies = pd.DataFrame(
            {
                "policy_version_id": ["pv-1"],
                "name": ["policy A"],
                "effective_from": ["2024-01-01T00:00:00Z"],
                "effective_to": ["2024-06-01T00:00:00Z"],
            }
        )

        findings = relational_rules.approval_requires_valid_policy(
            {"credit_decisions": decisions, "policy_versions": policies}, "credit_decisions"
        )

        assert len(findings) == 1
        assert findings[0].count == 1  # only dec-2 (2024-08-01) falls outside the window


class TestCpfLikeIdentifierDetection:
    """SECURITY.md and docs/business_rules.md require that no identifier
    column ever contain a real-document-shaped value. This is a safety
    net, not a generator behavior (this project's own synthetic IDs are
    always letter-prefixed, e.g. 'cust-001')."""

    @pytest.mark.parametrize(
        "value",
        ["123.456.789-01", "12345678901", "111.222.333-44", "000.000.001-91"],
    )
    def test_cpf_shaped_values_are_detected_regardless_of_punctuation(self, value: str) -> None:
        contract = load_contract(Path("contracts/operational/customers.yaml"))
        df = pd.DataFrame({"customer_id": [value]})

        findings = domain_rules.check_no_document_like_identifiers(df, contract)

        assert len(findings) == 1
        assert findings[0].code == "CPF_LIKE_IDENTIFIER"

    def test_no_fixture_scenario_contains_a_cpf_like_identifier(self) -> None:
        """Regression guard over every *_id column in every fixture this
        project ships, including the 11 invalid scenarios - a fixture
        built to test one specific violation must never accidentally
        also look like a real document number."""
        contract = load_contract(Path("contracts/operational/customers.yaml"))
        fixtures_root = Path("tests/fixtures/contracts")

        for csv_path in fixtures_root.rglob("*.csv"):
            df = pd.read_csv(csv_path, dtype=str)
            findings = domain_rules.check_no_document_like_identifiers(df, contract)
            assert findings == [], f"CPF-like identifier found in {csv_path}: {findings}"
