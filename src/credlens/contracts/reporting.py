"""Findings and validation reports shared by every rule module and the CLI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Finding:
    """One validation finding, with a stable machine-readable `code`."""

    code: str
    severity: str  # "error" | "warning" | "info"
    contract: str
    column: str | None
    message: str
    count: int | None = None
    total: int | None = None
    examples: tuple[str, ...] = ()

    @property
    def percentage(self) -> float | None:
        if self.count is None or not self.total:
            return None
        return round(self.count / self.total * 100, 4)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["percentage"] = self.percentage
        return payload


@dataclass(frozen=True)
class ValidationReport:
    contract: str
    mode: str  # "audit" | "strict"
    row_count: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(finding.severity == "error" for finding in self.findings)

    @property
    def passed(self) -> bool:
        """Whether this report would gate a strict-mode run.

        Always computed the same way regardless of mode - it is the CLI's
        job (not this property) to decide whether audit mode ignores this
        and exits 0 anyway. See src/credlens/cli.py.
        """
        return not self.has_errors

    def to_dict(self) -> dict[str, object]:
        return {
            "contract": self.contract,
            "mode": self.mode,
            "row_count": self.row_count,
            "passed": self.passed,
            "findings": [finding.to_dict() for finding in self.findings],
        }


def missing_tables_finding(contract_name: str, rule_code: str, needed: list[str]) -> Finding:
    """A rule that needs tables not supplied to this validation run.

    Not an error: this happens whenever `credlens contracts validate` is
    pointed at a single file rather than a scenario directory containing
    every related table. Reported as `info` so it's visible without
    failing anything.
    """
    return Finding(
        code="RULE_NOT_EVALUATED",
        severity="info",
        contract=contract_name,
        column=None,
        message=(
            f"Business rule '{rule_code}' was not evaluated: requires table(s) "
            f"{needed} not present in this validation run."
        ),
    )


def format_report(report: ValidationReport) -> str:
    lines = [
        f"{report.contract}  (mode={report.mode}, rows={report.row_count})",
    ]
    if not report.findings:
        lines.append("  No findings.")
        return "\n".join(lines)

    for finding in report.findings:
        location = f" [{finding.column}]" if finding.column else ""
        detail = ""
        if finding.count is not None:
            pct = f", {finding.percentage}%" if finding.percentage is not None else ""
            detail = f" ({finding.count}/{finding.total}{pct})"
        examples = f" e.g. {list(finding.examples)}" if finding.examples else ""
        prefix = f"  [{finding.severity:>7}] {finding.code}{location}: {finding.message}"
        lines.append(f"{prefix}{detail}{examples}")
    return "\n".join(lines)
