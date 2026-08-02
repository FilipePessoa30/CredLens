"""Release integrity validator (Phase 10 release-engineering layer).

Every check is LOCAL ONLY: reads already-tracked files via `git
ls-files`/the filesystem, never uploads content anywhere, never calls an
external secret-scanning service. This is an engineering checklist, not
a legal or security audit - see each check's own docstring for scope.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Denylist of KNOWN tolerance-masking shell idioms - shared with
# tests/test_ci_workflow_integrity.py, which parses THIS file's
# `CI_WORKFLOW_MASKING_PATTERNS` to guard against the exact regression
# Phase 10 gate B fixed (a `|| true` silently turning a real validation
# failure into a green check mark).
CI_WORKFLOW_MASKING_PATTERNS = ("|| true", "|| exit 0", "; true", "2>/dev/null; true", "|| echo")

_MAX_TRACKED_FILE_BYTES = 10 * 1024 * 1024  # 10 MiB
_SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "aws_access_key_id": re.compile(r"AKIA[0-9A-Z]{16}"),
    "generic_private_key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "slack_token": re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),
    "generic_api_key_assignment": re.compile(
        r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,}['\"]"
    ),
}
# Files/extensions where a "secret-shaped" string is expected and NOT a
# real finding (test fixtures, hashes, pseudonymized IDs, lockfiles).
_SECRET_SCAN_EXCLUDE_DIRS = ("tests/", "data/", "uv.lock", ".venv/")

_PII_LIKE_COLUMN_NAMES = {"cpf", "ssn", "social_security_number", "email", "phone", "full_name"}

_REQUIRED_BILINGUAL_REPORTS = (
    ("reports/modeling/model_card.md", "reports/modeling/model_card.pt-BR.md"),
    ("reports/modeling/technical_report.md", "reports/modeling/technical_report.pt-BR.md"),
    (
        "reports/model_validation/validation_report.md",
        "reports/model_validation/validation_report.pt-BR.md",
    ),
    ("reports/monitoring/monitoring_report.md", "reports/monitoring/monitoring_report.pt-BR.md"),
    (
        "reports/model_validation/remediation_report.md",
        "reports/model_validation/remediation_report.pt-BR.md",
    ),
    ("README.md", "README.pt-BR.md"),
)


@dataclass(frozen=True)
class IntegrityCheck:
    name: str
    status: str  # "pass" | "warning" | "fail"
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class ReleaseIntegrityReport:
    checks: list[IntegrityCheck] = field(default_factory=list)

    @property
    def has_failure(self) -> bool:
        return any(c.status == "fail" for c in self.checks)

    @property
    def has_warning(self) -> bool:
        return any(c.status == "warning" for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": "fail" if self.has_failure else ("warning" if self.has_warning else "pass"),
            "checks": [c.to_dict() for c in self.checks],
        }


def _tracked_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=repo_root, capture_output=True, text=True, check=True
    )
    return [line for line in result.stdout.splitlines() if line]


def _check_version_declared(repo_root: Path) -> IntegrityCheck:
    path = repo_root / "pyproject.toml"
    if not path.is_file():
        return IntegrityCheck("version_declared", "fail", "No pyproject.toml found.")
    pyproject = path.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    if match:
        return IntegrityCheck(
            "version_declared", "pass", f"pyproject.toml version={match.group(1)}"
        )
    return IntegrityCheck("version_declared", "fail", "No version found in pyproject.toml.")


def _check_lockfile_present(repo_root: Path) -> IntegrityCheck:
    path = repo_root / "uv.lock"
    if path.is_file():
        return IntegrityCheck("lockfile_present", "pass", "uv.lock is present.")
    return IntegrityCheck("lockfile_present", "fail", "uv.lock is missing.")


def _check_license_present(repo_root: Path) -> IntegrityCheck:
    path = repo_root / "LICENSE"
    if path.is_file() and path.stat().st_size > 0:
        return IntegrityCheck("license_present", "pass", "LICENSE file is present and non-empty.")
    return IntegrityCheck("license_present", "fail", "LICENSE file is missing or empty.")


def _check_no_secrets(repo_root: Path) -> IntegrityCheck:
    """Local regex scan over tracked TEXT files only - never uploads
    content anywhere. A denylist of well-known secret SHAPES (AWS keys,
    PEM private key headers, Slack tokens, generic
    `api_key="<20+ chars>"` assignments), not a general-purpose scanner -
    real findings should still be reviewed by a human, not auto-trusted."""
    hits: list[str] = []
    for rel_path in _tracked_files(repo_root):
        is_excluded = any(
            rel_path.startswith(prefix) or rel_path == prefix
            for prefix in _SECRET_SCAN_EXCLUDE_DIRS
        )
        if is_excluded:
            continue
        path = repo_root / rel_path
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern_name, pattern in _SECRET_PATTERNS.items():
            if pattern.search(text):
                hits.append(f"{rel_path} ({pattern_name})")
    if hits:
        return IntegrityCheck(
            "no_secrets_in_tracked_files",
            "fail",
            f"{len(hits)} possible secret-shaped string(s) found: {hits[:10]}",
        )
    return IntegrityCheck(
        "no_secrets_in_tracked_files",
        "pass",
        f"No known secret patterns found across {len(_tracked_files(repo_root))} tracked files.",
    )


def _check_no_large_tracked_files(repo_root: Path) -> IntegrityCheck:
    large = []
    for rel_path in _tracked_files(repo_root):
        path = repo_root / rel_path
        if path.is_file() and path.stat().st_size > _MAX_TRACKED_FILE_BYTES:
            large.append(f"{rel_path} ({path.stat().st_size / 1_048_576:.1f} MiB)")
    if large:
        return IntegrityCheck(
            "no_large_tracked_files", "warning", f"{len(large)} file(s) over 10 MiB: {large}"
        )
    return IntegrityCheck("no_large_tracked_files", "pass", "No tracked file exceeds 10 MiB.")


def _check_direct_dependencies_have_licenses(repo_root: Path) -> IntegrityCheck:
    """Phase 10B section 15: every DIRECTLY-declared dependency
    (`pyproject.toml`'s base `dependencies` + every extra + the `dev`
    dependency-group) must have an identified license or an explicit,
    visible finding here - never silently lumped in with the much larger,
    harder-to-audit set of transitive dependencies. A `warning`, not a
    `fail`: an unresolved license label is a metadata-quality gap this
    project can flag but not fix (it doesn't control the dependency's own
    packaging), and this is explicitly an engineering inventory, never a
    legal compliance determination."""
    from credlens.release.licenses import inventory_dependency_licenses

    inventory = inventory_dependency_licenses(repo_root)
    unresolved = [
        f"{d.name} {d.version} ({','.join(d.roles)})"
        for d in inventory.dependencies
        if d.compatibility == "direct_unknown_license_needs_review"
    ]
    if unresolved:
        return IntegrityCheck(
            "direct_dependencies_have_licenses",
            "warning",
            f"{len(unresolved)} direct dependencies have no identifiable license label: "
            f"{unresolved}.",
        )
    return IntegrityCheck(
        "direct_dependencies_have_licenses",
        "pass",
        f"All {inventory.direct_count} direct dependencies have an identified license.",
    )


def _check_no_pii_like_columns_in_demo_data(repo_root: Path) -> IntegrityCheck:
    demo_dir = repo_root / "dashboard" / "demo_data"
    if not demo_dir.is_dir():
        return IntegrityCheck(
            "no_pii_like_columns_in_demo_data",
            "warning",
            f"No demo data directory at '{demo_dir}'.",
        )
    hits = []
    for path in demo_dir.glob("*.parquet"):
        try:
            import pandas as pd

            columns = {c.lower() for c in pd.read_parquet(path).columns}
        except Exception:
            continue
        overlap = columns & _PII_LIKE_COLUMN_NAMES
        if overlap:
            hits.append(f"{path.name}: {sorted(overlap)}")
    if hits:
        return IntegrityCheck(
            "no_pii_like_columns_in_demo_data", "fail", f"PII-like column names found: {hits}"
        )
    return IntegrityCheck(
        "no_pii_like_columns_in_demo_data", "pass", "No PII-like column names in demo data."
    )


def _check_bilingual_reports_present(repo_root: Path) -> IntegrityCheck:
    missing = []
    for en_path, pt_path in _REQUIRED_BILINGUAL_REPORTS:
        if not (repo_root / en_path).is_file():
            missing.append(en_path)
        if not (repo_root / pt_path).is_file():
            missing.append(pt_path)
    if missing:
        return IntegrityCheck(
            "bilingual_reports_present", "fail", f"Missing report file(s): {missing}"
        )
    return IntegrityCheck(
        "bilingual_reports_present",
        "pass",
        f"All {len(_REQUIRED_BILINGUAL_REPORTS)} bilingual report pairs present.",
    )


def _check_model_artifacts_present(repo_root: Path) -> IntegrityCheck:
    required = [
        "reports/modeling/models/MODEL_behavioral_default_v1.joblib",
        "reports/modeling/models/MODEL_behavioral_default_v1.manifest.json",
    ]
    missing = [p for p in required if not (repo_root / p).is_file()]
    if missing:
        return IntegrityCheck("model_artifacts_present", "fail", f"Missing: {missing}")
    return IntegrityCheck(
        "model_artifacts_present", "pass", "Official candidate model artifacts present."
    )


def iter_workflow_run_steps(workflow: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Yields (job_name, step_name, run_text) for every step with a
    `run:` key - parses the ACTUAL YAML structure (never a raw-text
    substring scan, which would false-positive on a comment merely
    DISCUSSING `|| true`, e.g. this project's own gate-B removal notes)."""
    steps = []
    for job_name, job in workflow.get("jobs", {}).items():
        for step in job.get("steps", []):
            if "run" in step:
                steps.append((job_name, step.get("name", "<unnamed>"), step["run"]))
    return steps


def _check_ci_workflow_no_masking(repo_root: Path) -> IntegrityCheck:
    path = repo_root / ".github" / "workflows" / "ci.yml"
    if not path.is_file():
        return IntegrityCheck("ci_workflow_no_masking", "fail", "No CI workflow file found.")
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    hits = []
    for job_name, step_name, run_text in iter_workflow_run_steps(workflow):
        for pattern in CI_WORKFLOW_MASKING_PATTERNS:
            if pattern in run_text:
                hits.append(f"job={job_name} step={step_name!r} pattern={pattern!r}")
    if hits:
        return IntegrityCheck(
            "ci_workflow_no_masking", "fail", f"Tolerance-masking pattern(s) found: {hits}"
        )
    return IntegrityCheck("ci_workflow_no_masking", "pass", "No tolerance-masking pattern found.")


def _check_coverage_gate(repo_root: Path) -> IntegrityCheck:
    """Phase 10B - `RC_1.0.0rc1_bc33e939` was declared ready with real
    coverage at 94% because this check DID NOT EXIST; see `reports/
    release/release_errata.json`. Reads a persisted, source-fingerprint-
    stamped snapshot (`credlens release measure-coverage`) rather than a
    hand-typed number - a missing or stale snapshot fails exactly like a
    genuinely low one."""
    from credlens.release.coverage_gate import check_coverage_gate

    result = check_coverage_gate(repo_root=repo_root)
    return IntegrityCheck("coverage_gate", result.status, result.detail)


def _check_monitoring_detection_gate(repo_root: Path) -> IntegrityCheck:
    """Phase 10B - `RC_1.0.0rc1_bc33e939` was declared ready with a real
    `scenario_detection_rate` of 0.5 because this check DID NOT EXIST; see
    `reports/release/release_errata.json`. Reads persisted, source-
    fingerprint-stamped detection/false-alert evidence (`credlens monitor
    evaluate-detection`/`evaluate-false-alerts`) - never a hand-typed
    number."""
    from credlens.release.monitoring_gate import check_monitoring_detection_gate

    result = check_monitoring_detection_gate(repo_root=repo_root)
    return IntegrityCheck("monitoring_detection_gate", result.status, result.detail)


def run_release_integrity_checks(repo_root: Path | None = None) -> ReleaseIntegrityReport:
    repo_root = repo_root or Path.cwd()
    checks = [
        _check_version_declared(repo_root),
        _check_lockfile_present(repo_root),
        _check_license_present(repo_root),
        _check_no_secrets(repo_root),
        _check_no_large_tracked_files(repo_root),
        _check_direct_dependencies_have_licenses(repo_root),
        _check_no_pii_like_columns_in_demo_data(repo_root),
        _check_bilingual_reports_present(repo_root),
        _check_model_artifacts_present(repo_root),
        _check_ci_workflow_no_masking(repo_root),
        _check_coverage_gate(repo_root),
        _check_monitoring_detection_gate(repo_root),
    ]
    return ReleaseIntegrityReport(checks=checks)
