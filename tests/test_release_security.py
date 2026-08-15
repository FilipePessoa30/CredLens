"""Tests for credlens.release.security (Fase 14 security gate) - parses
real-shaped pip-audit/Trivy JSON and applies this project's blocking
policy. Fixtures below mirror the ACTUAL schema observed from real
`pip-audit --format json` and `trivy image --format json` runs during
Fase 14 (pyarrow/gitpython CVEs found and fixed - see CHANGELOG), not
invented shapes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from credlens.release.security import (
    SecurityGateError,
    evaluate_security_gate,
    parse_pip_audit_report,
    parse_trivy_report,
    write_security_audit,
)

_PIP_AUDIT_CLEAN = {"dependencies": [{"name": "requests", "version": "2.34.2", "vulns": []}]}

_PIP_AUDIT_WITH_FIX = {
    "dependencies": [
        {
            "name": "pyarrow",
            "version": "18.1.0",
            "vulns": [
                {
                    "id": "PYSEC-2026-113",
                    "fix_versions": ["23.0.1"],
                    "aliases": ["GHSA-rgxp-2hwp-jwgg", "CVE-2026-25087"],
                }
            ],
        }
    ]
}

_PIP_AUDIT_NO_FIX = {
    "dependencies": [
        {
            "name": "somepkg",
            "version": "1.0.0",
            "vulns": [{"id": "PYSEC-2026-999", "fix_versions": [], "aliases": []}],
        }
    ]
}


def _write(tmp_path: Path, name: str, payload: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestParsePipAuditReport:
    def test_clean_report_has_no_findings(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "clean.json", _PIP_AUDIT_CLEAN)
        assert parse_pip_audit_report(path) == []

    def test_finding_with_a_fix_is_blocking(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "vuln.json", _PIP_AUDIT_WITH_FIX)
        findings = parse_pip_audit_report(path)
        assert len(findings) == 1
        f = findings[0]
        assert f.package == "pyarrow"
        assert f.identifier == "PYSEC-2026-113"
        assert f.fixed_version == "23.0.1"
        assert f.blocking is True
        assert f.severity == "HIGH"

    def test_finding_with_no_fix_is_not_blocking(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "nofix.json", _PIP_AUDIT_NO_FIX)
        findings = parse_pip_audit_report(path)
        assert len(findings) == 1
        assert findings[0].blocking is False
        assert findings[0].fixed_version is None

    def test_missing_report_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SecurityGateError, match="not found"):
            parse_pip_audit_report(tmp_path / "does_not_exist.json")

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(SecurityGateError, match="not valid JSON"):
            parse_pip_audit_report(path)


_TRIVY_CLEAN = {"Results": [{"Target": "app", "Class": "lang-pkgs", "Type": "python-pkg"}]}

_TRIVY_CRITICAL = {
    "Results": [
        {
            "Target": "app",
            "Class": "lang-pkgs",
            "Type": "python-pkg",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2099-0001",
                    "PkgName": "badpkg",
                    "InstalledVersion": "1.0.0",
                    "FixedVersion": "1.0.1",
                    "Severity": "CRITICAL",
                }
            ],
        }
    ]
}

_TRIVY_CRITICAL_NO_FIX_NOT_EXCEPTED = {
    "Results": [
        {
            "Target": "app",
            "Class": "lang-pkgs",
            "Type": "python-pkg",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2099-9999",
                    "PkgName": "some-other-package",
                    "InstalledVersion": "1.0.0",
                    "FixedVersion": "",
                    "Severity": "CRITICAL",
                }
            ],
        }
    ]
}

# Matches a REAL entry in credlens.release.security._DOCUMENTED_EXCEPTIONS
# (found by an actual Trivy scan of credlens:1.0.0-candidate, Fase 14).
_TRIVY_CRITICAL_DOCUMENTED_EXCEPTION_NO_FIX = {
    "Results": [
        {
            "Target": "debian 13.6",
            "Class": "os-pkgs",
            "Type": "debian",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2026-13221",
                    "PkgName": "perl-base",
                    "InstalledVersion": "5.40.1-6",
                    "FixedVersion": "",
                    "Severity": "CRITICAL",
                }
            ],
        }
    ]
}

_TRIVY_CRITICAL_SAME_ID_BUT_NOW_FIXED = {
    "Results": [
        {
            "Target": "debian 13.6",
            "Class": "os-pkgs",
            "Type": "debian",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2026-13221",
                    "PkgName": "perl-base",
                    "InstalledVersion": "5.40.1-6",
                    "FixedVersion": "5.40.1-7",
                    "Severity": "CRITICAL",
                }
            ],
        }
    ]
}

# Matches a REAL "not_applicable_to_runtime" entry in _DOCUMENTED_EXCEPTIONS
# (found by the real CI Trivy scan of credlens:1.0.0-candidate, Fase 14 -
# pip's own pre-upgrade vendored msgpack, confirmed absent from the live
# container's filesystem despite `docker save` preserving the old layer).
_TRIVY_HIGH_NOT_APPLICABLE_EXCEPTION_WITH_A_FIX_AVAILABLE = {
    "Results": [
        {
            "Target": "Python",
            "Class": "lang-pkgs",
            "Type": "python-pkg",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "GHSA-6v7p-g79w-8964",
                    "PkgName": "msgpack",
                    "InstalledVersion": "1.1.2",
                    "FixedVersion": "1.2.1",
                    "Severity": "HIGH",
                }
            ],
        }
    ]
}

_TRIVY_HIGH_NO_FIX = {
    "Results": [
        {
            "Target": "debian 13",
            "Class": "os-pkgs",
            "Type": "debian",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2099-0002",
                    "PkgName": "libsomething",
                    "InstalledVersion": "2.0",
                    "FixedVersion": "",
                    "Severity": "HIGH",
                }
            ],
        }
    ]
}

_TRIVY_MEDIUM_ONLY = {
    "Results": [
        {
            "Target": "app",
            "Class": "lang-pkgs",
            "Type": "python-pkg",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2099-0003",
                    "PkgName": "mediumpkg",
                    "InstalledVersion": "1.0.0",
                    "FixedVersion": "1.0.1",
                    "Severity": "MEDIUM",
                }
            ],
        }
    ]
}

_TRIVY_WITH_SECRET = {
    "Results": [
        {
            "Target": "app/.env",
            "Class": "secret",
            "Secrets": [{"RuleID": "aws-access-key-id", "Category": "AWS"}],
        }
    ]
}


class TestParseTrivyReport:
    def test_clean_report_has_no_findings(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "clean.json", _TRIVY_CLEAN)
        assert parse_trivy_report(path) == []

    def test_critical_is_always_blocking(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "critical.json", _TRIVY_CRITICAL)
        findings = parse_trivy_report(path)
        assert len(findings) == 1
        assert findings[0].severity == "CRITICAL"
        assert findings[0].blocking is True

    def test_critical_with_no_fix_and_no_documented_exception_is_blocking(
        self, tmp_path: Path
    ) -> None:
        path = _write(tmp_path, "critical_nofix.json", _TRIVY_CRITICAL_NO_FIX_NOT_EXCEPTED)
        findings = parse_trivy_report(path)
        assert len(findings) == 1
        assert findings[0].blocking is True

    def test_critical_matching_a_documented_exception_with_no_fix_is_not_blocking(
        self, tmp_path: Path
    ) -> None:
        """Fase 14 section 13 - a CRITICAL finding with genuinely no fix
        available CAN be a documented, non-blocking exception, but only
        when it matches a specific, individually-justified entry in
        `_DOCUMENTED_EXCEPTIONS` - never a blanket allowlist."""
        path = _write(
            tmp_path, "critical_excepted.json", _TRIVY_CRITICAL_DOCUMENTED_EXCEPTION_NO_FIX
        )
        findings = parse_trivy_report(path)
        assert len(findings) == 1
        assert findings[0].blocking is False
        assert "documented exception" in findings[0].reason

    def test_a_documented_exception_reverts_to_blocking_once_a_fix_exists(
        self, tmp_path: Path
    ) -> None:
        """The exception only ever excuses "no fix exists" - the same
        CVE/package becomes blocking again the moment a fix is
        published, with no code change needed here."""
        path = _write(tmp_path, "now_fixed.json", _TRIVY_CRITICAL_SAME_ID_BUT_NOW_FIXED)
        findings = parse_trivy_report(path)
        assert len(findings) == 1
        assert findings[0].blocking is True

    def test_not_applicable_to_runtime_exception_ignores_fix_availability(
        self, tmp_path: Path
    ) -> None:
        """Unlike a `no_fix_available` exception, a `not_applicable_to_
        runtime` one (e.g. a stale Docker-layer artifact confirmed
        absent from the live container) stays non-blocking even though
        a fix genuinely exists elsewhere - the justification is about
        exploitability/presence, not fix availability."""
        path = _write(
            tmp_path,
            "not_applicable.json",
            _TRIVY_HIGH_NOT_APPLICABLE_EXCEPTION_WITH_A_FIX_AVAILABLE,
        )
        findings = parse_trivy_report(path)
        assert len(findings) == 1
        assert findings[0].fixed_version == "1.2.1"
        assert findings[0].blocking is False
        assert "documented exception" in findings[0].reason

    def test_high_without_a_fix_is_not_blocking(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "high_nofix.json", _TRIVY_HIGH_NO_FIX)
        findings = parse_trivy_report(path)
        assert len(findings) == 1
        assert findings[0].severity == "HIGH"
        assert findings[0].fixed_version is None
        assert findings[0].blocking is False

    def test_medium_is_never_blocking(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "medium.json", _TRIVY_MEDIUM_ONLY)
        findings = parse_trivy_report(path)
        assert len(findings) == 1
        assert findings[0].blocking is False


class TestEvaluateSecurityGate:
    def test_two_clean_reports_pass(self, tmp_path: Path) -> None:
        pip_path = _write(tmp_path, "pip.json", _PIP_AUDIT_CLEAN)
        trivy_path = _write(tmp_path, "trivy.json", _TRIVY_CLEAN)
        result = evaluate_security_gate(
            pip_audit_report_path=pip_path, trivy_report_path=trivy_path
        )
        assert result.passed is True
        assert result.blocking_findings == []

    def test_a_missing_report_fails_the_gate(self, tmp_path: Path) -> None:
        pip_path = _write(tmp_path, "pip.json", _PIP_AUDIT_CLEAN)
        result = evaluate_security_gate(
            pip_audit_report_path=pip_path, trivy_report_path=tmp_path / "missing.json"
        )
        assert result.passed is False
        assert result.trivy_report_present is False

    def test_a_blocking_pip_audit_finding_fails_the_gate(self, tmp_path: Path) -> None:
        pip_path = _write(tmp_path, "pip.json", _PIP_AUDIT_WITH_FIX)
        trivy_path = _write(tmp_path, "trivy.json", _TRIVY_CLEAN)
        result = evaluate_security_gate(
            pip_audit_report_path=pip_path, trivy_report_path=trivy_path
        )
        assert result.passed is False
        assert len(result.blocking_findings) == 1

    def test_a_blocking_trivy_finding_fails_the_gate(self, tmp_path: Path) -> None:
        pip_path = _write(tmp_path, "pip.json", _PIP_AUDIT_CLEAN)
        trivy_path = _write(tmp_path, "trivy.json", _TRIVY_CRITICAL)
        result = evaluate_security_gate(
            pip_audit_report_path=pip_path, trivy_report_path=trivy_path
        )
        assert result.passed is False

    def test_a_non_blocking_finding_alone_still_passes(self, tmp_path: Path) -> None:
        pip_path = _write(tmp_path, "pip.json", _PIP_AUDIT_NO_FIX)
        trivy_path = _write(tmp_path, "trivy.json", _TRIVY_HIGH_NO_FIX)
        result = evaluate_security_gate(
            pip_audit_report_path=pip_path, trivy_report_path=trivy_path
        )
        assert result.passed is True
        assert len(result.findings) == 2
        assert result.blocking_findings == []

    def test_a_secret_in_the_image_fails_the_gate_even_with_no_vulnerabilities(
        self, tmp_path: Path
    ) -> None:
        pip_path = _write(tmp_path, "pip.json", _PIP_AUDIT_CLEAN)
        trivy_path = _write(tmp_path, "trivy.json", _TRIVY_WITH_SECRET)
        result = evaluate_security_gate(
            pip_audit_report_path=pip_path, trivy_report_path=trivy_path
        )
        assert result.passed is False
        assert result.secret_found_in_image is True


class TestWriteSecurityAudit:
    def test_writes_a_readable_json_report(self, tmp_path: Path) -> None:
        pip_path = _write(tmp_path, "pip.json", _PIP_AUDIT_CLEAN)
        trivy_path = _write(tmp_path, "trivy.json", _TRIVY_CLEAN)
        result = evaluate_security_gate(
            pip_audit_report_path=pip_path, trivy_report_path=trivy_path
        )
        out_path = write_security_audit(result, repo_root=tmp_path)
        assert out_path.is_file()
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["passed"] is True
