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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SNAPSHOT_PATH = Path("reports/release/coverage_snapshot.json")
MIN_COVERAGE_PERCENT = 95.0


class CoverageGateError(Exception):
    """Raised when a coverage snapshot cannot be built, read, or is invalid."""


@dataclass(frozen=True)
class CoverageSnapshot:
    coverage_percent: float
    total_statements: int
    covered_statements: int
    test_count: int
    source_snapshot_fingerprint: str
    measured_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage_percent": round(self.coverage_percent, 4),
            "total_statements": self.total_statements,
            "covered_statements": self.covered_statements,
            "test_count": self.test_count,
            "source_snapshot_fingerprint": self.source_snapshot_fingerprint,
            "measured_at_utc": self.measured_at_utc,
        }


def build_coverage_snapshot(
    coverage_json_path: Path, *, test_count: int, repo_root: Path | None = None
) -> CoverageSnapshot:
    """Reads a REAL `coverage.json` (coverage.py's own `--cov-report=
    json` output, produced by an actual full `pytest --cov` run - never
    hand-typed) and stamps it with the CURRENT source-snapshot
    fingerprint, so a later staleness check can tell whether the code has
    changed since this number was measured."""
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

    snapshot = compute_source_snapshot(repo_root)
    return CoverageSnapshot(
        coverage_percent=float(totals["percent_covered"]),
        total_statements=int(totals["num_statements"]),
        covered_statements=int(totals["covered_lines"]),
        test_count=test_count,
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
    repo_root = repo_root or Path.cwd()
    path = repo_root / SNAPSHOT_PATH
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return CoverageSnapshot(**raw)


@dataclass(frozen=True)
class CoverageGateResult:
    status: str  # "pass" | "fail"
    detail: str


def check_coverage_gate(
    *, min_coverage_percent: float = MIN_COVERAGE_PERCENT, repo_root: Path | None = None
) -> CoverageGateResult:
    """The gate `credlens.release.integrity`/`manifest` enforce: no
    snapshot -> fail; a snapshot whose `source_snapshot_fingerprint`
    doesn't match the CURRENT working tree -> fail (stale evidence, e.g.
    left over from before a later code change); coverage below
    `min_coverage_percent` -> fail. Never a guessed or hand-typed
    number."""
    from credlens.release.source_snapshot import compute_source_snapshot

    repo_root = repo_root or Path.cwd()
    snapshot = load_coverage_snapshot(repo_root=repo_root)
    if snapshot is None:
        return CoverageGateResult(
            "fail",
            "No coverage snapshot found - run 'credlens release measure-coverage' after a real "
            "'pytest --cov-report=json:coverage.json' run.",
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
    if snapshot.coverage_percent < min_coverage_percent:
        return CoverageGateResult(
            "fail",
            f"Coverage is {snapshot.coverage_percent:.2f}% - below the required "
            f"{min_coverage_percent:.0f}% ({snapshot.covered_statements}/"
            f"{snapshot.total_statements} statements, {snapshot.test_count} tests).",
        )
    return CoverageGateResult(
        "pass",
        f"Coverage is {snapshot.coverage_percent:.2f}% (>= {min_coverage_percent:.0f}% required), "
        f"measured fresh against the current source snapshot.",
    )
