"""Source snapshot fingerprint (Phase 10B - Release Candidate Acceptance
Remediation).

`credlens.release.manifest.ReleaseManifest.base_commit` is `git rev-parse
HEAD` - a real, correct anchor when the working tree is clean, but
misleading on its own when it is not: a release built from a dirty
working tree (uncommitted changes on top of `base_commit`) would carry
the SAME `base_commit` as a release built from the clean commit itself,
even though their actual file contents differ. This module fingerprints
the CONTENT every tracked file currently has on disk - including
uncommitted changes - so two releases can only share a
`source_snapshot_fingerprint` if their tracked file contents are
byte-identical, dirty tree or not.

Deliberately excludes: caches (`__pycache__`, `.pytest_cache`, `.mypy_
cache`, `.ruff_cache`), `.venv`, coverage artifacts (`coverage.json`,
`.coverage`, `htmlcov/`), any path under `data/`/`reports/` that is
itself a build/run OUTPUT rather than versioned source (these are
git-ignored in this repository already, so `git ls-files` never lists
them - the exclusion list here is a second, explicit guard against ever
including something timestamp-bearing or non-deterministic even if it
were ever accidentally tracked).

Also excludes the evidence/output files this fingerprint mechanism
itself produces or that the release process regenerates every run with
non-deterministic content (`coverage_snapshot.json`, `detection_
evaluation.json`, `false_alert_study.json`, `release_manifest.json`,
`sbom.cyclonedx.json` - the last one carries a fresh UUID `serialNumber`
every generation, by CycloneDX's own spec) - a real, empirically-found
self-reference bug (Phase 10B): each evidence file stamps itself with a
snapshot of "every tracked file", but if these files are themselves
tracked, writing ANY one of them changes the tracked-file set, which
changes the fingerprint the OTHERS just stamped themselves with - no
sequence of re-runs can ever converge on all of them agreeing, since
each write invalidates the rest. Excluding these (evidence/output ABOUT
the code, never the code itself, and in SBOM's case never even
deterministic) breaks the cycle; a genuine source/config change
(including a change to calibrated thresholds these evidence files
actually depend on, e.g. `reference/*__alert_thresholds.json`) still
correctly changes the fingerprint and invalidates stale evidence.

Fase 12 added `license_inventory.json` and `SHA256SUMS` to this same
exclusion list - the identical self-reference bug, found while fixing
the `v1.0.0rc2` Pre-Release's stale-checksums incident:
`license_inventory.json` has no `source_snapshot_fingerprint` field of
its own, but it IS one of `credlens.release.checksums.
CANONICAL_RELEASE_ASSETS`, so regenerating it (even to fully
deterministic, unchanged content, since it carries no timestamp either)
still touches the tracked-file set the coverage/monitoring gates had
already stamped themselves against moments earlier - and `SHA256SUMS`
is, by construction, generated LAST (`credlens release checksums`),
strictly after `release_manifest.json` has already recorded a
fingerprint, so including it here would make that just-recorded
fingerprint stale the instant `SHA256SUMS` itself is written, with no
possible correct ordering that converges.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from credlens.release.canonical_content import canonicalize_content

_EXCLUDED_PATH_FRAGMENTS = (
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "coverage.json",
    ".coverage",
    "htmlcov/",
    "reports/release/coverage_snapshot.json",
    "reports/monitoring/detection_evaluation.json",
    "reports/monitoring/false_alert_study.json",
    "reports/release/release_manifest.json",
    "reports/release/sbom.cyclonedx.json",
    "reports/release/license_inventory.json",
    "reports/release/SHA256SUMS",
    "reports/release/security_audit.json",
)


class SourceSnapshotError(Exception):
    """Raised when the source snapshot fingerprint cannot be computed."""


@dataclass(frozen=True)
class SourceSnapshot:
    fingerprint: str
    n_files: int
    base_commit: str
    working_tree_clean: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "n_files": self.n_files,
            "base_commit": self.base_commit,
            "working_tree_clean": self.working_tree_clean,
        }


def _tracked_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=repo_root, capture_output=True, text=True, check=True
    )
    return sorted(line for line in result.stdout.splitlines() if line)


def compute_source_snapshot(repo_root: Path | None = None) -> SourceSnapshot:
    """Hashes the CURRENT content of every git-tracked file (sorted by
    path, path+content both fed into the digest so a rename changes the
    fingerprint too) into one SHA256 - never just `git rev-parse HEAD`,
    which is blind to uncommitted changes.

    Content is canonicalized (`canonicalize_content`) before hashing,
    NOT read raw off disk - Fase 11B found that a Windows working tree
    (`core.autocrlf=true`) holds CRLF for files git itself stores as LF
    (`.gitattributes`: `* text=auto eol=lf`), so hashing raw bytes made
    this fingerprint unrecoverably different between a Windows and a
    Linux checkout of the exact same commit, with zero real content
    difference - the direct cause of `coverage_gate`/
    `monitoring_detection_gate` reporting STALE on every Linux CI run.

    A file still in git's index but removed from the working tree
    without staging the deletion (`rm` without `git rm`) is a real,
    legitimate uncommitted change, not an error condition - it is simply
    excluded from the digest, exactly like any other content change would
    shift the fingerprint. Only a genuine I/O failure on a file that DOES
    exist (permissions, a locked file) raises `SourceSnapshotError`."""
    repo_root = repo_root or Path.cwd()
    files = [
        rel_path
        for rel_path in _tracked_files(repo_root)
        if not any(fragment in rel_path for fragment in _EXCLUDED_PATH_FRAGMENTS)
    ]
    digest = hashlib.sha256()
    n_hashed = 0
    for rel_path in files:
        path = repo_root / rel_path
        if not path.is_file():
            continue
        try:
            content = canonicalize_content(rel_path, path.read_bytes())
        except OSError as exc:
            raise SourceSnapshotError(f"Tracked file '{rel_path}' could not be read.") from exc
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(content)
        digest.update(b"\x00")
        n_hashed += 1

    head_result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True
    )
    status_result = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo_root, capture_output=True, text=True, check=True
    )
    return SourceSnapshot(
        fingerprint=digest.hexdigest(),
        n_files=n_hashed,
        base_commit=head_result.stdout.strip(),
        working_tree_clean=not status_result.stdout.strip(),
    )
