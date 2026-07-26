"""Safe, injectable test isolation for the generation/warehouse pipeline
(Phase 6 gate B).

The Phase 5 final report documented a real, structural problem: because
CredLens run ids are fully deterministic - `(scenario, scale, seed,
config_hash)` and nothing else - any test using the same coordinates as
an "official" demonstration run (e.g. `scenario=baseline, scale=smoke,
seed=2026`) legitimately recreates, and then cleans up, the EXACT SAME
directory an official run/suite/analytical build also occupies. No test's
own cleanup logic was ever wrong in isolation; the shared root itself was
the hazard.

This module provides the two pieces needed to eliminate that hazard
structurally rather than by picking seeds that are unlikely to collide:

- `isolated_output_dirs()` / `isolated_manifest_dir()`: context managers
  or plain values a test can pass to
  `credlens.generation.orchestrator.generate_scenario`/`generate_baseline`
  (via `config_override=credlens.generation.config.with_output_dirs(...)`)
  and `credlens.generation.suite.generate_suite`/`load_suite_manifest`
  (via their own `output_dirs`/`manifest_dir` parameters) so generated
  data and suite manifests are written under a caller-supplied root -
  normally a pytest `tmp_path` - and NEVER under the shared
  `data/synthetic/`, `data/synthetic_truth/`, or
  `reports/synthetic_validation/suites/` roots real runs/suites/
  analytical builds use.
- `safe_rmtree()`: a cleanup function that refuses to delete anything
  outside an explicitly allowed root, and additionally refuses if that
  allowed root itself IS (or contains, or is contained by) one of the
  project's known protected roots - so a cleanup fixture cannot
  accidentally widen its own blast radius back to the shared roots this
  module exists to protect, even if a future edit mistakenly passes one
  in.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from credlens.generation.writers import PathSafetyError, resolve_within_directory

# The only two roots a legacy (not-yet-isolated-root) test is ever
# allowed to narrowly reach into via delete_exact_run_dir() - deliberately
# an allowlist of exact values, not "anything under data/".
_LEGACY_DELETE_ALLOWED_ROOTS = ("data/synthetic", "data/synthetic_truth")
_RUN_ID_PATTERN = re.compile(r"^RUN_[A-Za-z0-9_]+$")

# Every root real runs/suites/quarantine incidents/analytical builds/
# versioned reports write to - never a valid target OR allowed_root for
# safe_rmtree(), regardless of how a caller arrived at the path.
PROTECTED_ROOTS: tuple[str, ...] = (
    "data/synthetic",
    "data/synthetic_truth",
    "data/quarantine",
    "data/warehouse",
    "reports",
)


class UnsafeCleanupError(Exception):
    """Raised when a cleanup call would touch a path outside its
    explicitly allowed root, or when the allowed root itself overlaps a
    protected root."""


def _resolved_protected_roots(repo_root: Path) -> list[Path]:
    return [(repo_root / p).resolve() for p in PROTECTED_ROOTS]


def _overlaps(a: Path, b: Path) -> bool:
    """True if `a` and `b` are the same path, or one contains the other."""
    if a == b:
        return True
    try:
        a.relative_to(b)
        return True
    except ValueError:
        pass
    try:
        b.relative_to(a)
        return True
    except ValueError:
        pass
    return False


def assert_root_is_safe(allowed_root: Path, *, repo_root: Path | None = None) -> Path:
    """Raises UnsafeCleanupError if `allowed_root` equals, contains, or is
    contained by any PROTECTED_ROOTS entry. Returns the resolved root on
    success - callers should use the returned value, not re-resolve it
    themselves, so there is exactly one place path resolution happens."""
    repo_root = (repo_root or Path.cwd()).resolve()
    resolved_root = allowed_root.resolve()
    for protected in _resolved_protected_roots(repo_root):
        if _overlaps(resolved_root, protected):
            raise UnsafeCleanupError(
                f"Refusing to treat '{resolved_root}' as an allowed cleanup root - it "
                f"overlaps the protected root '{protected}'. Use an isolated root (e.g. "
                "pytest's tmp_path), never a path under data/synthetic, "
                "data/synthetic_truth, data/quarantine, data/warehouse, or reports."
            )
    return resolved_root


def safe_rmtree(path: Path, *, allowed_root: Path, repo_root: Path | None = None) -> None:
    """Deletes `path` (a directory) only if it resolves to a location
    inside `allowed_root`, and only if `allowed_root` itself is not a
    protected root. Both relative and absolute `path`/`allowed_root`
    values are resolved before comparison, so a `..`-based traversal
    cannot escape the allowed root undetected."""
    resolved_root = assert_root_is_safe(allowed_root, repo_root=repo_root)
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise UnsafeCleanupError(
            f"Refusing to delete '{resolved_path}': it is not inside the allowed "
            f"root '{resolved_root}'."
        ) from exc
    if resolved_path.exists():
        shutil.rmtree(resolved_path)


def delete_exact_run_dir(operational_root: Path, run_id: str) -> None:
    """Narrow escape hatch for legacy tests that exercise a CLI command
    which does not yet accept an isolated output root (e.g. `credlens
    synthetic monte-carlo`, which always runs against the real
    data/synthetic/ tree) - deletes exactly one, precisely computed run
    directory, never a pattern or substring match.

    Deliberately stricter than safe_rmtree(): `operational_root` must be
    exactly one of the two legitimate top-level roots (an allowlist, not
    'anything not in PROTECTED_ROOTS'), `run_id` must match CredLens' own
    `RUN_...` id shape (rejects an empty string, which would otherwise
    resolve to operational_root itself), and the resolved target must be
    a DIRECT child of operational_root - never a nested or traversed
    path. This is the same safety property the Phase 5 fix already
    achieved by computing exact run ids instead of a substring match;
    this function makes that pattern reusable and independently tested
    rather than hand-rolled per test file."""
    normalized = str(operational_root).replace("\\", "/").rstrip("/")
    if normalized not in _LEGACY_DELETE_ALLOWED_ROOTS:
        raise UnsafeCleanupError(
            f"delete_exact_run_dir only accepts operational_root in "
            f"{_LEGACY_DELETE_ALLOWED_ROOTS}, got '{operational_root}'."
        )
    if not _RUN_ID_PATTERN.match(run_id):
        raise UnsafeCleanupError(
            f"Refusing to delete run_id '{run_id}': does not match CredLens' own "
            f"run id shape ({_RUN_ID_PATTERN.pattern})."
        )
    try:
        target = resolve_within_directory(operational_root, run_id)
    except PathSafetyError as exc:
        raise UnsafeCleanupError(str(exc)) from exc
    if target.parent != operational_root.resolve():
        raise UnsafeCleanupError(
            f"Refusing to delete '{target}': not a direct child of '{operational_root}'."
        )
    if target.exists():
        shutil.rmtree(target)


def isolated_output_dirs(tmp_path: Path) -> tuple[Path, Path]:
    """(operational_dir, truth_dir) pair rooted under a caller-supplied
    isolated directory (normally pytest's own tmp_path, which is itself
    already unique per test) - the value to pass as
    generate_scenario(..., config_override=with_output_dirs(config,
    operational_dir=..., truth_dir=...)) or
    generate_suite(..., output_dirs=...)."""
    return tmp_path / "synthetic", tmp_path / "synthetic_truth"


def isolated_manifest_dir(tmp_path: Path) -> Path:
    """Where an isolated test's own suite manifest should be written -
    the value to pass as generate_suite(..., manifest_dir=...) /
    load_suite_manifest(..., manifest_dir=...)."""
    return tmp_path / "reports" / "suites"
