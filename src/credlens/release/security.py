"""Security audit gate (Fase 14) - judges real `pip-audit`/Trivy JSON
reports against this project's own blocking policy. Never runs a
scanner itself: those are external, official/widely-recognized tools
(`pip-audit` for the effective Python runtime dependency set, Trivy for
the built Docker image) invoked separately (CLI/CI step) - this module
only parses their OWN output and decides pass/fail, exactly the same
"trust the real tool, judge its real output" shape as `credlens.release.
coverage_gate` trusts a real `pytest --cov-report=json` run.

Blocking policy (this project's own, not a generic CVSS cutoff):
  - a CRITICAL finding is blocking UNLESS it matches a narrow, explicit,
    individually-justified entry in `_DOCUMENTED_EXCEPTIONS` below (see
    that tuple's own docstring - "no fix exists anywhere yet" is real
    grounds for a documented exception, never a blanket allowlist);
  - a HIGH finding is blocking when a fix is already available (nothing
    to document an exception for - the fix should just be applied, the
    same real fix this phase applied for pyarrow/gitpython/uv/pip/
    setuptools/wheel);
  - a HIGH finding with NO fix available yet, or a scanner that could
    not examine its target at all, is handled explicitly (non-blocking
    vs. hard-blocking respectively) - never silently treated as "no
    vulnerabilities found".
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


ExceptionBasis = Literal["no_fix_available", "not_applicable_to_runtime"]


@dataclass(frozen=True)
class SecurityException:
    """One individually-justified, narrow blocking exception - never a
    blanket allowlist (Fase 14 section 13's explicit requirement: every
    entry needs its own CVE/package/justification/impact/review date).
    `basis` distinguishes the two grounds section 13 actually allows,
    since they behave differently as new scan data arrives:
      - `"no_fix_available"`: valid only while `fixed_version is None`
        for that exact finding - the moment upstream ships a fix, this
        exception stops applying and the finding reverts to blocking
        automatically, no code change needed here (a fix existing is
        precisely what invalidates this specific justification).
      - `"not_applicable_to_runtime"`: applies regardless of fix
        availability - the justification is about the vulnerable code
        never actually executing in this image (e.g. a build-time-only
        tool, or a stale/superseded artifact confirmed absent from the
        live filesystem), which a fix being published elsewhere does
        not change. Still bounded by `review_by`, re-checked by hand.
    """

    identifier: str
    package: str
    basis: ExceptionBasis
    justification: str
    impact: str
    review_by: str


# Fase 14 - found by a real Trivy scan of credlens:1.0.0-candidate
# (2026-08-14, Debian 13.6 base image): perl-base 5.40.1-6 carries these
# 4 CRITICAL CVEs with NO fix published in the Debian security archive
# as of the scan date (Trivy itself reports `FixedVersion` empty for
# each). perl-base is a base-OS package pulled in transitively by
# Debian's own package-management tooling (dpkg/apt dependencies) - this
# image never invokes perl at runtime (no application code path calls
# it; the dashboard/CLI/warehouse-build pipeline is pure Python + a
# compiled dbt-duckdb adapter). Re-evaluated on every scan, not assumed
# permanently safe.
_DOCUMENTED_EXCEPTIONS: tuple[SecurityException, ...] = (
    SecurityException(
        identifier="CVE-2026-13221",
        package="perl-base",
        basis="no_fix_available",
        justification="No fix published in the Debian 13 security archive as of the scan "
        "date; perl-base is pulled in transitively by Debian's own package tooling "
        "(dpkg/apt), not invoked by any application code path in this image.",
        impact="perl is never executed at runtime by the dashboard, CLI, or warehouse-build "
        "pipeline (pure Python + a compiled dbt-duckdb adapter) - no realistic exploitation "
        "path in this image's actual usage.",
        review_by="2026-11-14",
    ),
    SecurityException(
        identifier="CVE-2026-42496",
        package="perl-base",
        basis="no_fix_available",
        justification="No fix published in the Debian 13 security archive as of the scan "
        "date; same transitive-dependency situation as CVE-2026-13221.",
        impact="Same as CVE-2026-13221 - perl is never executed at runtime in this image.",
        review_by="2026-11-14",
    ),
    SecurityException(
        identifier="CVE-2026-57433",
        package="perl-base",
        basis="no_fix_available",
        justification="No fix published in the Debian 13 security archive as of the scan "
        "date; same transitive-dependency situation as CVE-2026-13221.",
        impact="Same as CVE-2026-13221 - perl is never executed at runtime in this image.",
        review_by="2026-11-14",
    ),
    SecurityException(
        identifier="CVE-2026-8376",
        package="perl-base",
        basis="no_fix_available",
        justification="No fix published in the Debian 13 security archive as of the scan "
        "date; same transitive-dependency situation as CVE-2026-13221.",
        impact="Same as CVE-2026-13221 - perl is never executed at runtime in this image.",
        review_by="2026-11-14",
    ),
    # Fase 14 - a SECOND, different real finding from the same CI Trivy
    # scan, after the fixes above were applied: `docker save`'s exported
    # tarball preserves every individual Docker layer, including ones a
    # LATER layer overwrites/removes in the final merged filesystem view
    # (`pip install --upgrade pip` uninstalls the base image's original
    # pip package, whose OWN vendored `pip/_vendor/msgpack` bundle and
    # Python's own `ensurepip/_bundled/setuptools-*.whl` sit in an
    # EARLIER layer) - Trivy's language-package detector, scanning the
    # tarball layer-by-layer, still finds these stale, superseded files.
    # Confirmed - not assumed - via two independent checks: (1) manually
    # inspecting the saved image tarball's individual `layer.tar`
    # members directly (a build tool, not runtime), finding the old
    # versions ONLY in an early layer that a later layer's whiteout
    # entry removes from the merged view; (2) `find / -iname
    # 'msgpack*dist-info' -o -iname 'setuptools*dist-info'` run INSIDE a
    # live container from this exact image, which finds only the
    # correctly upgraded versions (pip 26.2.1 - which no longer vendors
    # msgpack at all - and setuptools 84.0.0) - no trace of the old
    # ones in the actual, active, running filesystem this container
    # ever executes from. This is the FIRST exception-clause ground
    # ("comprovadamente não aplicável ao runtime"), not the second.
    SecurityException(
        identifier="GHSA-6v7p-g79w-8964",
        package="msgpack",
        basis="not_applicable_to_runtime",
        justification="Confirmed via direct layer-by-layer tarball inspection to be pip's "
        "OWN pre-upgrade vendored copy (pip/_vendor/msgpack) in an early Docker layer, "
        "superseded by `pip install --upgrade pip` in a later layer - `docker save` "
        "preserves the old layer's content even though it is absent from the final merged "
        "filesystem. Confirmed absent from a live container's actual filesystem (`find / "
        "-iname msgpack*dist-info` finds only the correct, current dashboard-venv copy).",
        impact="Not applicable to the runtime - pip's own internal msgpack usage never "
        "executes in this image at all (pip itself is a build-time tool, not invoked by the "
        "running dashboard/CLI), and the specific vulnerable file does not exist in the "
        "image's actual, active filesystem.",
        review_by="2026-11-14",
    ),
    SecurityException(
        identifier="CVE-2025-47273",
        package="setuptools",
        basis="not_applicable_to_runtime",
        justification="Confirmed via direct layer-by-layer tarball inspection to be an "
        "early-layer artifact (Python's own `ensurepip/_bundled/setuptools-*.whl`, an inert "
        "wheel FILE the standard library ships, never installed/imported/executed) and/or "
        "the base image's pre-upgrade setuptools, superseded by `pip install --upgrade "
        "setuptools` in a later layer - same `docker save` layer-preservation situation as "
        "the msgpack entry above. Confirmed absent from a live container's actual "
        "filesystem (`find / -iname setuptools*dist-info` finds only the correct, current "
        "84.0.0 install).",
        impact="Not applicable to the runtime - a dormant wheel file inside Python's own "
        "stdlib `ensurepip` module (never invoked by this image's entrypoint or any "
        "application code path) is not the same as an installed, importable package "
        "actually exposed to attacker-controlled input.",
        review_by="2026-11-14",
    ),
)
_EXCEPTIONS_BY_KEY: dict[tuple[str, str], SecurityException] = {
    (e.identifier, e.package): e for e in _DOCUMENTED_EXCEPTIONS
}


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
            identifier = str(vuln.get("VulnerabilityID", "unknown"))
            package = str(vuln.get("PkgName", "unknown"))
            exception = _EXCEPTIONS_BY_KEY.get((identifier, package))

            # The exception check comes FIRST, before severity/fix-
            # availability - Fase 14 section 13's two grounds behave
            # differently as new scan data arrives (see `SecurityException`'s
            # own docstring): a `not_applicable_to_runtime` exception
            # applies regardless of fix availability; a `no_fix_available`
            # exception applies ONLY while no fix actually exists yet,
            # reverting to blocking automatically the moment one ships.
            applies = exception is not None and (
                exception.basis == "not_applicable_to_runtime"
                or (exception.basis == "no_fix_available" and fixed_version is None)
            )
            if applies:
                assert exception is not None  # narrows the type for mypy
                blocking = False
                reason = (
                    f"{severity}, documented exception ({exception.basis}) - see "
                    "credlens.release.security._DOCUMENTED_EXCEPTIONS"
                )
            elif severity == "CRITICAL":
                blocking = True
                if fixed_version:
                    reason = f"CRITICAL severity with a fix available at {fixed_version} - apply it"
                else:
                    reason = "CRITICAL, no fix available, and not a documented exception - blocking"
            elif severity == "HIGH" and fixed_version:
                blocking = True
                reason = f"HIGH severity with a fix available at {fixed_version} - apply it"
            elif severity == "HIGH":
                blocking = False
                reason = "no fix version published yet - documented, not blocking"
            else:
                blocking = False
                reason = f"{severity} severity - recorded, not blocking on its own"
            findings.append(
                SecurityFinding(
                    source="trivy",
                    identifier=identifier,
                    package=package,
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
