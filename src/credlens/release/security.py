"""Security audit gate (Fase 14) - judges real `pip-audit`/Trivy JSON
reports against this project's own blocking policy. Never runs a
scanner itself: those are external, official/widely-recognized tools
(`pip-audit` for the effective Python runtime dependency set, Trivy for
the built Docker image) invoked separately (CLI/CI step) - this module
only parses their OWN output and decides pass/fail, exactly the same
"trust the real tool, judge its real output" shape as `credlens.release.
coverage_gate` trusts a real `pytest --cov-report=json` run.

Blocking policy (this project's own, not a generic CVSS cutoff):
  - any CRITICAL finding is blocking;
  - a HIGH finding is blocking when a fix is already available (nothing
    to document an exception for - the fix should just be applied, the
    same real fix this phase applied for pyarrow/gitpython);
  - a HIGH/CRITICAL finding with NO fix available yet, or a scanner
    that could not examine its target at all, is handled explicitly
    (documented-not-blocking vs. hard-blocking respectively) - never
    silently treated as "no vulnerabilities found".
  - MEDIUM/LOW/UNKNOWN findings are recorded but never block on their
    own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]
_SEVERITY_ORDER: dict[Severity, int] = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "UNKNOWN": 0,
}


class SecurityGateError(Exception):
    """Raised when a security report is missing or cannot be parsed."""


@dataclass(frozen=True)
class SecurityFinding:
    source: Literal["pip-audit", "trivy"]
    identifier: str
    package: str
    installed_version: str
    fixed_version: str | None
    severity: Severity
    blocking: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "identifier": self.identifier,
            "package": self.package,
            "installed_version": self.installed_version,
            "fixed_version": self.fixed_version,
            "severity": self.severity,
            "blocking": self.blocking,
            "reason": self.reason,
        }


def _read_json(path: Path, tool_name: str) -> dict[str, Any]:
    if not path.is_file():
        raise SecurityGateError(f"{tool_name} report not found at '{path}'.")
    try:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SecurityGateError(f"{tool_name} report at '{path}' is not valid JSON.") from exc
    return payload


def parse_pip_audit_report(path: Path) -> list[SecurityFinding]:
    """Parses `pip-audit --format json` output:
    `{"dependencies": [{"name", "version", "vulns": [{"id",
    "fix_versions", ...}]}]}`. pip-audit's own CLI JSON does not carry
    a normalized CVSS severity field - every real finding it reports is
    a known, applicable advisory (PyPA Advisory DB / OSV), so it is
    conservatively treated as HIGH, never silently downgraded to MEDIUM/
    LOW for lack of a severity field this tool simply doesn't emit."""
    payload = _read_json(path, "pip-audit")
    findings: list[SecurityFinding] = []
    for dep in payload.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            fix_versions = vuln.get("fix_versions") or []
            fixed_version = fix_versions[0] if fix_versions else None
            blocking = fixed_version is not None
            reason = (
                f"fix available at {fixed_version} - apply it, not an exception"
                if blocking
                else "no fix version published yet by the advisory - documented, not blocking"
            )
            findings.append(
                SecurityFinding(
                    source="pip-audit",
                    identifier=str(vuln.get("id", "unknown")),
                    package=str(dep.get("name", "unknown")),
                    installed_version=str(dep.get("version", "unknown")),
                    fixed_version=fixed_version,
                    severity="HIGH",
                    blocking=blocking,
                    reason=reason,
                )
            )
    return findings


def parse_trivy_report(path: Path) -> list[SecurityFinding]:
    """Parses `trivy image --format json` output: a top-level `Results`
    list, each with its own `Vulnerabilities` list (`VulnerabilityID`,
    `PkgName`, `InstalledVersion`, `FixedVersion`, `Severity`) - the
    same shape whether the result entry is an OS-package (`os-pkgs`,
    e.g. Debian) or a language-package (`lang-pkgs`, e.g. `python-pkg`)
    target; both are real "shipped in the runtime image" findings and
    are not distinguished further by this policy."""
    payload = _read_json(path, "trivy")
    findings: list[SecurityFinding] = []
    for result in payload.get("Results") or []:
        for vuln in result.get("Vulnerabilities") or []:
            severity_raw = str(vuln.get("Severity", "UNKNOWN")).upper()
            severity: Severity = severity_raw if severity_raw in _SEVERITY_ORDER else "UNKNOWN"
            fixed_version = vuln.get("FixedVersion") or None
            blocking = severity == "CRITICAL" or (severity == "HIGH" and fixed_version is not None)
            if severity == "CRITICAL":
                reason = "CRITICAL severity is always blocking"
            elif severity == "HIGH" and fixed_version:
                reason = f"HIGH severity with a fix available at {fixed_version} - apply it"
            elif severity in ("HIGH", "CRITICAL"):
                reason = "no fix version published yet - documented, not blocking"
            else:
                reason = f"{severity} severity - recorded, not blocking on its own"
            findings.append(
                SecurityFinding(
                    source="trivy",
                    identifier=str(vuln.get("VulnerabilityID", "unknown")),
                    package=str(vuln.get("PkgName", "unknown")),
                    installed_version=str(vuln.get("InstalledVersion", "unknown")),
                    fixed_version=fixed_version,
                    severity=severity,
                    blocking=blocking,
                    reason=reason,
                )
            )
    return findings


def _trivy_found_a_secret(path: Path) -> bool:
    """True if the same Trivy report includes any `Secrets` finding
    (only present when the scan was invoked with the `secret` scanner
    in addition to `vuln`) - a secret baked into the image is always
    blocking, regardless of any vulnerability-severity policy."""
    payload = _read_json(path, "trivy")
    return any(result.get("Secrets") for result in payload.get("Results") or [])


@dataclass(frozen=True)
class SecurityAuditResult:
    findings: list[SecurityFinding] = field(default_factory=list)
    pip_audit_report_present: bool = False
    trivy_report_present: bool = False
    secret_found_in_image: bool = False
    generated_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def blocking_findings(self) -> list[SecurityFinding]:
        return sorted(
            (f for f in self.findings if f.blocking),
            key=lambda f: _SEVERITY_ORDER[f.severity],
            reverse=True,
        )

    @property
    def passed(self) -> bool:
        return (
            self.pip_audit_report_present
            and self.trivy_report_present
            and not self.secret_found_in_image
            and not self.blocking_findings
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "pip_audit_report_present": self.pip_audit_report_present,
            "trivy_report_present": self.trivy_report_present,
            "secret_found_in_image": self.secret_found_in_image,
            "total_findings": len(self.findings),
            "blocking_findings": [f.to_dict() for f in self.blocking_findings],
            "non_blocking_findings": [f.to_dict() for f in self.findings if not f.blocking],
            "generated_at_utc": self.generated_at_utc,
        }


def evaluate_security_gate(
    *, pip_audit_report_path: Path, trivy_report_path: Path
) -> SecurityAuditResult:
    """The single entry point `credlens release security` (and the CI
    security job) call: reads both real scanner reports and returns a
    pass/fail decision. A MISSING report is itself a blocking condition
    (`*_report_present=False`) - "the scanner didn't run" is never
    silently equivalent to "nothing found"."""
    pip_audit_present = pip_audit_report_path.is_file()
    trivy_present = trivy_report_path.is_file()

    findings: list[SecurityFinding] = []
    secret_found = False

    if pip_audit_present:
        findings.extend(parse_pip_audit_report(pip_audit_report_path))
    if trivy_present:
        findings.extend(parse_trivy_report(trivy_report_path))
        secret_found = _trivy_found_a_secret(trivy_report_path)

    return SecurityAuditResult(
        findings=findings,
        pip_audit_report_present=pip_audit_present,
        trivy_report_present=trivy_present,
        secret_found_in_image=secret_found,
    )


def write_security_audit(result: SecurityAuditResult, *, repo_root: Path | None = None) -> Path:
    repo_root = repo_root or Path.cwd()
    out_path = repo_root / "reports" / "release" / "security_audit.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return out_path
