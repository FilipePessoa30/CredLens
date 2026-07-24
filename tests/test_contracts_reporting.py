"""Tests for credlens.contracts.reporting: Finding, ValidationReport, format_report."""

from __future__ import annotations

from credlens.contracts.reporting import (
    Finding,
    ValidationReport,
    format_report,
    missing_tables_finding,
)


class TestFinding:
    def test_percentage_none_without_count(self) -> None:
        finding = Finding(code="X", severity="error", contract="c", column=None, message="m")
        assert finding.percentage is None

    def test_percentage_none_with_zero_total(self) -> None:
        finding = Finding(
            code="X", severity="error", contract="c", column=None, message="m", count=0, total=0
        )
        assert finding.percentage is None

    def test_percentage_computed(self) -> None:
        finding = Finding(
            code="X", severity="error", contract="c", column=None, message="m", count=3, total=12
        )
        assert finding.percentage == 25.0

    def test_to_dict_includes_percentage(self) -> None:
        finding = Finding(
            code="X", severity="error", contract="c", column="col", message="m", count=1, total=4
        )
        payload = finding.to_dict()
        assert payload["percentage"] == 25.0
        assert payload["code"] == "X"
        assert payload["column"] == "col"

    def test_finding_is_frozen(self) -> None:
        finding = Finding(code="X", severity="error", contract="c", column=None, message="m")
        try:
            finding.code = "Y"  # type: ignore[misc]
            raised = False
        except Exception:
            raised = True
        assert raised


class TestValidationReport:
    def test_no_findings_passes(self) -> None:
        report = ValidationReport(contract="c", mode="strict", row_count=10)
        assert report.has_errors is False
        assert report.passed is True

    def test_error_finding_fails(self) -> None:
        finding = Finding(code="X", severity="error", contract="c", column=None, message="m")
        report = ValidationReport(contract="c", mode="strict", row_count=10, findings=[finding])
        assert report.has_errors is True
        assert report.passed is False

    def test_warning_only_still_passes(self) -> None:
        finding = Finding(code="X", severity="warning", contract="c", column=None, message="m")
        report = ValidationReport(contract="c", mode="strict", row_count=10, findings=[finding])
        assert report.has_errors is False
        assert report.passed is True

    def test_passed_is_mode_independent(self) -> None:
        """`passed` reflects rule outcomes only - it is the CLI, not this
        property, that decides whether audit mode ignores errors when
        setting the process exit code (see cli.py's _cmd_contracts_validate)."""
        finding = Finding(code="X", severity="error", contract="c", column=None, message="m")
        audit_report = ValidationReport(contract="c", mode="audit", row_count=1, findings=[finding])
        assert audit_report.passed is False

    def test_to_dict_shape(self) -> None:
        finding = Finding(code="X", severity="error", contract="c", column=None, message="m")
        report = ValidationReport(contract="c", mode="strict", row_count=5, findings=[finding])
        payload = report.to_dict()
        assert payload["contract"] == "c"
        assert payload["mode"] == "strict"
        assert payload["row_count"] == 5
        assert payload["passed"] is False
        assert len(payload["findings"]) == 1  # type: ignore[arg-type]


def test_missing_tables_finding_is_info_severity() -> None:
    finding = missing_tables_finding("applications", "some_rule", ["credit_decisions"])
    assert finding.severity == "info"
    assert finding.code == "RULE_NOT_EVALUATED"
    assert "credit_decisions" in finding.message


def test_format_report_no_findings() -> None:
    report = ValidationReport(contract="applications", mode="audit", row_count=3)
    text = format_report(report)
    assert "applications" in text
    assert "No findings." in text


def test_format_report_with_findings_includes_code_and_counts() -> None:
    finding = Finding(
        code="DOMAIN_VIOLATION",
        severity="error",
        contract="applications",
        column="channel",
        message="bad value",
        count=2,
        total=10,
        examples=("carrier_pigeon",),
    )
    report = ValidationReport(
        contract="applications", mode="strict", row_count=10, findings=[finding]
    )
    text = format_report(report)

    assert "DOMAIN_VIOLATION" in text
    assert "[channel]" in text
    assert "2/10" in text
    assert "carrier_pigeon" in text
