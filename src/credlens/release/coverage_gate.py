"""Coverage acceptance gate (Phase 10B - Release Candidate Acceptance
Remediation).

`RC_1.0.0rc1_bc33e939` was declared `release_candidate_ready_with_
limitations` with real, measured coverage at 94% - `credlens.release.
manifest.decide_readiness` never read a coverage number at all, so no
threshold could ever become a blocker (see `reports/release/
release_errata.json`). This module makes coverage an enforced, evidenced
gate: `credlens release measure-coverage` reads a REAL `coverage.json`
(produced by `pytest --cov-report=json:coverage.json`) and writes a
snapshot stamped with the CURRENT source-snapshot fingerprint; `credlens
release validate` then refuses a stale snapshot (one whose fingerprint no
longer matches the working tree) exactly as strictly as it refuses a
missing one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SNAPSHOT_PATH = Path("reports/release/coverage_snapshot.json")
MIN_COVERAGE_PERCENT = 95.0


class CoverageGateError(Exception):
    """Raised when a coverage snapshot cannot be built, read, or is invalid."""


def _project_version(repo_root: Path) -> str:
    path = repo_root / "pyproject.toml"
    if not path.is_file():
        return "unknown"
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "unknown"


@dataclass(frozen=True)
class CoverageSnapshot:
    coverage_percent: float
    total_statements: int
    covered_statements: int
    missing_statements: int
    test_count: int
    command: str
    pytest_exit_code: int
    project_version: str
    source_snapshot_fingerprint: str
    measured_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage_percent": round(self.coverage_percent, 4),
            "total_statements": self.total_statements,
            "covered_statements": self.covered_statements,
            "missing_statements": self.missing_statements,
            "test_count": self.test_count,
            "command": self.command,
            "pytest_exit_code": self.pytest_exit_code,
            "project_version": self.project_version,
            "source_snapshot_fingerprint": self.source_snapshot_fingerprint,
            "measured_at_utc": self.measured_at_utc,
        }


def build_coverage_snapshot(
    coverage_json_path: Path,
    *,
    test_count: int,
    command: str,
    pytest_exit_code: int,
    repo_root: Path | None = None,
) -> CoverageSnapshot:
    """Reads a REAL `coverage.json` (coverage.py's own `--cov-report=
    json` output, produced by an actual full `pytest --cov` run - never
    hand-typed) and stamps it with the CURRENT source-snapshot
    fingerprint, the exact `command` that produced it, that command's own
    `pytest_exit_code`, and the current `project_version` - so a later
    check can tell whether the code changed since measurement (staleness),
    whether the underlying run actually passed in full (exit code), and
    whether it was measured against the version currently declared."""
    from datetime import UTC, datetime

    from credlens.release.source_snapshot import compute_source_snapshot

    repo_root = repo_root or Path.cwd()
    if not coverage_json_path.is_file():
        raise CoverageGateError(f"No coverage.json found at '{coverage_json_path}'.")
    try:
        raw = json.loads(coverage_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CoverageGateError(f"'{coverage_json_path}' is not valid JSON.") from exc
    totals = raw.get("totals")
    if not totals:
        raise CoverageGateError(f"'{coverage_json_path}' has no 'totals' section.")

    total_statements = int(totals["num_statements"])
    covered_statements = int(totals["covered_lines"])
    missing_statements = int(totals.get("missing_lines", total_statements - covered_statements))
    if covered_statements + missing_statements != total_statements:
        raise CoverageGateError(
            f"'{coverage_json_path}' is internally inconsistent: covered_lines "
            f"({covered_statements}) + missing_lines ({missing_statements}) != num_statements "
            f"({total_statements})."
        )

    snapshot = compute_source_snapshot(repo_root)
    return CoverageSnapshot(
        coverage_percent=float(totals["percent_covered"]),
        total_statements=total_statements,
        covered_statements=covered_statements,
        missing_statements=missing_statements,
        test_count=test_count,
        command=command,
        pytest_exit_code=pytest_exit_code,
        project_version=_project_version(repo_root),
        source_snapshot_fingerprint=snapshot.fingerprint,
        measured_at_utc=datetime.now(UTC).isoformat(),
    )


def write_coverage_snapshot(snapshot: CoverageSnapshot, *, repo_root: Path | None = None) -> Path:
    repo_root = repo_root or Path.cwd()
    path = repo_root / SNAPSHOT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
    return path


def load_coverage_snapshot(*, repo_root: Path | None = None) -> CoverageSnapshot | None:
    """Returns `None` (treated identically to "no snapshot" by
    `check_coverage_gate`) for a missing file OR one that cannot be
    parsed into the CURRENT `CoverageSnapshot` shape - e.g. one written
    by an older version of this module, before a field was added. A
    schema-incompatible snapshot is not valid evidence; failing the gate
    gracefully is correct, an unhandled `TypeError` crashing the whole
    release-integrity run is not."""
    repo_root = repo_root or Path.cwd()
    path = repo_root / SNAPSHOT_PATH
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        return CoverageSnapshot(**raw)
    except TypeError:
        return None


@dataclass(frozen=True)
class CoverageGateResult:
    status: str  # "pass" | "fail"
    detail: str


def check_coverage_gate(
    *, min_coverage_percent: float = MIN_COVERAGE_PERCENT, repo_root: Path | None = None
) -> CoverageGateResult:
    """The gate `credlens.release.integrity`/`manifest` enforce: no
    snapshot -> fail; a non-zero `pytest_exit_code` -> fail (a failing or
    otherwise incomplete run must never produce accepted evidence); a
    `command` missing the enforced `--cov-fail-under` flag or filtering
    tests with `-k`/`-m` -> fail (evidence must come from the full suite,
    run with the threshold actually enforced); a snapshot whose
    `source_snapshot_fingerprint` doesn't match the CURRENT working tree
    -> fail (stale evidence, e.g. left over from before a later code
    change); a snapshot measured against a different `project_version`
    than the one currently declared -> fail (stale-by-version, e.g. left
    over from before an RC version bump); coverage below
    `min_coverage_percent`, compared as the full-precision float `coverage.
    py` itself reports (never `percent_covered_display`, which rounds) ->
    fail. Never a guessed or hand-typed number."""
    from credlens.release.source_snapshot import compute_source_snapshot

    repo_root = repo_root or Path.cwd()
    snapshot = load_coverage_snapshot(repo_root=repo_root)
    if snapshot is None:
        return CoverageGateResult(
            "fail",
            "No coverage snapshot found - run 'credlens release measure-coverage' after a real "
            "'pytest --cov-report=json:coverage.json' run.",
        )
    if snapshot.pytest_exit_code != 0:
        return CoverageGateResult(
            "fail",
            f"The pytest run that produced this coverage snapshot exited with status "
            f"{snapshot.pytest_exit_code} (non-zero) - at least one test failed, or the run was "
            "otherwise incomplete. Re-run the full suite until it exits 0, then re-measure.",
        )
    if "--cov-fail-under" not in snapshot.command:
        return CoverageGateResult(
            "fail",
            f"The recorded command ('{snapshot.command}') does not include '--cov-fail-under' - "
            "coverage must be measured with the enforced threshold flag present, not a bare "
            "'--cov' run.",
        )
    if re.search(r"(^|\s)-[km]\b", snapshot.command):
        return CoverageGateResult(
            "fail",
            f"The recorded command ('{snapshot.command}') filters tests with -k/-m - coverage "
            "must be measured against the FULL suite, never a filtered subset.",
        )
    current = compute_source_snapshot(repo_root)
    if snapshot.source_snapshot_fingerprint != current.fingerprint:
        return CoverageGateResult(
            "fail",
            "Coverage snapshot is STALE - its source_snapshot_fingerprint "
            f"({snapshot.source_snapshot_fingerprint[:12]}...) does not match the current "
            f"working tree ({current.fingerprint[:12]}...). Re-run 'pytest --cov-report="
            "json:coverage.json' and 'credlens release measure-coverage'.",
        )
    current_version = _project_version(repo_root)
    if snapshot.project_version != current_version:
        return CoverageGateResult(
            "fail",
            f"Coverage snapshot was measured against project_version="
            f"'{snapshot.project_version}', but the current project_version is "
            f"'{current_version}' - re-measure after a version bump.",
        )
    if snapshot.coverage_percent < min_coverage_percent:
        return CoverageGateResult(
            "fail",
            f"Coverage is {snapshot.coverage_percent:.4f}% - below the required "
            f"{min_coverage_percent:.2f}% ({snapshot.covered_statements}/"
            f"{snapshot.total_statements} statements, {snapshot.missing_statements} missing, "
            f"{snapshot.test_count} tests).",
        )
    return CoverageGateResult(
        "pass",
        f"Coverage is {snapshot.coverage_percent:.4f}% (>= {min_coverage_percent:.2f}% required), "
        f"measured fresh against the current source snapshot and project_version="
        f"'{current_version}'.",
    )
