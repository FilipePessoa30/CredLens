"""Canonical release inventory (Fase 11A - Immutable Release Identity
and GitHub Publication Preflight).

Classifies every file destined for publication - tracked AND untracked -
into one of 12 categories, and computes a deterministic fingerprint over
the INTENDED release content. Complements `credlens.release.
source_snapshot` (which fingerprints only currently-tracked file content,
used by the coverage/monitoring staleness gates) rather than replacing
it: this inventory additionally classifies untracked files not yet
`git add`-ed, is explicit about WHY each path is included or excluded
(not just a single opaque digest), and never touches the git index -
classification is pure path/size analysis, read-only filesystem access.

Self-reference (same real bug Phase 10B found for `source_snapshot`):
evidence this release-engineering layer itself produces would, if
hashed, invalidate its own fingerprint on every write. `SELF_REFERENTIAL_
EVIDENCE` paths are still classified and LISTED as `release_evidence`
(an operator can see they exist) but excluded from the fingerprint
payload specifically - the two-layer split section 7 of the Fase 11A
brief calls for.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

INVENTORY_SCHEMA_VERSION = 1

Classification = Literal[
    "release_source",
    "release_config",
    "release_sql",
    "release_test",
    "release_documentation",
    "release_asset",
    "release_evidence",
    "runtime_data_excluded",
    "temporary_excluded",
    "secret_excluded",
    "large_file_excluded",
    "unresolved",
]

# Classifications whose matching entries are part of the PUBLISHED
# release payload - everything else is deliberately excluded from it.
INCLUDED_CLASSIFICATIONS: frozenset[Classification] = frozenset(
    {
        "release_source",
        "release_config",
        "release_sql",
        "release_test",
        "release_documentation",
        "release_asset",
        "release_evidence",
    }
)

LARGE_FILE_LIMIT_BYTES = 10 * 1024 * 1024  # matches integrity.py's own tracked-file limit

# Evidence this release-engineering layer itself produces - excluded
# from the FINGERPRINT payload only (still classified/listed as
# `release_evidence`; Phase 10B's self-reference cycle is about hashing
# a file into its own stamped fingerprint, not about listing it).
SELF_REFERENTIAL_EVIDENCE = (
    "reports/release/coverage_snapshot.json",
    "reports/monitoring/detection_evaluation.json",
    "reports/monitoring/false_alert_study.json",
    "reports/release/release_manifest.json",
    "reports/release/sbom.cyclonedx.json",
    "reports/release/staging_plan.txt",
    "reports/release/release_inventory.json",
)

# Known-ephemeral TRACKED paths found during the Fase 11A audit - real,
# accidentally-committed test/run byproducts (these directories are not
# covered by .gitignore, unlike data/warehouse/ or data/synthetic/,
# which are), never genuine release content regardless of their current
# tracked status. See the Fase 11A report for exact counts.
_TEMPORARY_TRACKED_PREFIXES = (
    "reports/modeling/quarantine/",
    "reports/monitoring/runs/",
    "reports/monitoring/alerts/",
)
_TEMPORARY_TRACKED_EXACT = ("coverage.json",)

_TEMPORARY_PATH_FRAGMENTS = (
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".coverage",
    "coverage.xml",
    "htmlcov/",
    ".ipynb_checkpoints",
    "_executed.ipynb",
)

_RUNTIME_DATA_PREFIXES = (
    "data/warehouse/",
    "data/synthetic/",
    "data/synthetic_truth/",
    "warehouse/target/",
    "warehouse/dbt_packages/",
    "warehouse/profiles.yml",
)

_SECRET_NAME_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "credentials.json",
    "secrets.yaml",
    "secrets.yml",
)

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".svg", ".gif", ".ico")

_CONFIG_ROOT_FILES = (
    "pyproject.toml",
    "uv.lock",
    ".gitignore",
    ".dockerignore",
    ".editorconfig",
    ".gitattributes",
    ".python-version",
    "Makefile",
    "Dockerfile.dashboard",
    ".env.example",
    "SECURITY.md",
    "LICENSE",
)

# Deliberately-versioned exceptions under data/ (see .gitignore's own
# `!data/metadata/...` carve-outs) - provenance/schema/manifest records,
# never the raw or acquired dataset itself.
_DATA_METADATA_PREFIX = "data/metadata/"


class InventoryError(Exception):
    """Raised when the release inventory cannot be built."""


def classify_path(rel_path: str) -> tuple[Classification, str]:
    """Pure function: a repo-relative, forward-slash path -> (classification,
    human-readable reason). No filesystem access - size-based reclassification
    (`large_file_excluded`) happens in `build_release_inventory`, which knows
    the real size."""
    p = rel_path.replace("\\", "/").lstrip("/")
    name = p.rsplit("/", 1)[-1]

    for pattern in _SECRET_NAME_PATTERNS:
        if fnmatch.fnmatch(name, pattern) and name != ".env.example":
            return "secret_excluded", f"filename matches secret pattern '{pattern}'"

    for prefix in _TEMPORARY_TRACKED_PREFIXES:
        if p.startswith(prefix):
            return (
                "temporary_excluded",
                f"ephemeral test/monitoring-run byproduct under '{prefix}' - "
                "accidentally trackable (not covered by .gitignore), never release content",
            )
    if p in _TEMPORARY_TRACKED_EXACT:
        return (
            "temporary_excluded",
            "regenerated build artifact (coverage report) - must never be part of "
            "the release payload, regardless of its current tracked status",
        )
    if any(fragment in p for fragment in _TEMPORARY_PATH_FRAGMENTS):
        return "temporary_excluded", "cache/build/execution artifact"

    for prefix in _RUNTIME_DATA_PREFIXES:
        if p.startswith(prefix):
            return "runtime_data_excluded", f"runtime/generated data under '{prefix}'"
    if p.startswith(_DATA_METADATA_PREFIX):
        return "release_config", "data provenance/schema/manifest record (never raw data)"
    if p.startswith("data/") and p not in ("data/README.md", "data/.gitkeep"):
        return "runtime_data_excluded", "raw/acquired dataset, never redistributed"

    if p.startswith("tests/"):
        return "release_test", "under tests/"

    if p.startswith("dashboard/demo_data/"):
        return "release_asset", "curated demo aggregate package (small, deliberately shipped)"

    # Images are release_asset regardless of which directory holds them
    # (docs/, reports/, dashboard/) - checked before any directory-prefix
    # rule below so a screenshot under docs/ or reports/ is never
    # miscategorized as documentation/evidence just because of its parent.
    if any(p.endswith(ext) for ext in _IMAGE_EXTENSIONS):
        return "release_asset", "image asset"

    if p.startswith("src/") or p.startswith("dashboard/"):
        return "release_source", "Python source"

    if p.startswith("warehouse/"):
        return "release_sql", "dbt project file (SQL/YAML/macros/seeds)"

    if p.startswith(".github/"):
        return "release_config", "CI/CD workflow definition"
    if p.startswith("config/"):
        return "release_config", "project configuration"
    if p.startswith("contracts/"):
        return "release_config", "data contract definition"
    if p in _CONFIG_ROOT_FILES:
        return "release_config", "project configuration"

    # reports/**/*.md is evidence (a validation/monitoring/analysis
    # report), checked before the generic ".md -> documentation" rule
    # below, which is meant for root-level/docs-level narrative docs.
    if p.startswith("reports/"):
        return "release_evidence", "official evidence/report artifact"

    if p.startswith("notebooks/") and p.endswith(".ipynb"):
        return "release_documentation", "source notebook"
    if p.startswith("docs/"):
        return "release_documentation", "documentation"
    if p.startswith("analysis/") or p.startswith("scripts/"):
        return "release_documentation", "specification/script documentation"
    if p.endswith(".md"):
        return "release_documentation", "documentation (Markdown)"

    return "unresolved", "no classification rule matched this path - requires human review"


@dataclass(frozen=True)
class InventoryEntry:
    path: str
    file_mode: str
    size_bytes: int
    sha256: str
    classification: Classification
    reason: str
    tracking_status: Literal["tracked", "untracked"]
    requires_human_review: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "file_mode": self.file_mode,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "classification": self.classification,
            "reason": self.reason,
            "tracking_status": self.tracking_status,
            "requires_human_review": self.requires_human_review,
        }


@dataclass(frozen=True)
class ReleaseInventory:
    schema_version: int
    entries: tuple[InventoryEntry, ...]
    fingerprint: str

    @property
    def included(self) -> tuple[InventoryEntry, ...]:
        return tuple(e for e in self.entries if e.classification in INCLUDED_CLASSIFICATIONS)

    @property
    def excluded(self) -> tuple[InventoryEntry, ...]:
        return tuple(
            e
            for e in self.entries
            if e.classification not in INCLUDED_CLASSIFICATIONS and e.classification != "unresolved"
        )

    @property
    def unresolved(self) -> tuple[InventoryEntry, ...]:
        return tuple(e for e in self.entries if e.classification == "unresolved")

    @property
    def needs_human_review(self) -> tuple[InventoryEntry, ...]:
        return tuple(e for e in self.entries if e.requires_human_review)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "fingerprint": self.fingerprint,
            "n_entries": len(self.entries),
            "n_included": len(self.included),
            "n_excluded": len(self.excluded),
            "n_unresolved": len(self.unresolved),
            "n_needs_human_review": len(self.needs_human_review),
            "entries": [e.to_dict() for e in self.entries],
        }


def _tracked_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=repo_root, capture_output=True, text=True, check=True
    )
    return sorted(line for line in result.stdout.splitlines() if line)


def _untracked_files(repo_root: Path) -> list[str]:
    """Real, uncommitted new files - `git status --porcelain --untracked-
    files=all` never touches the index (read-only), unlike `git add`."""
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    paths = []
    for line in result.stdout.splitlines():
        if line.startswith("??"):
            paths.append(line[3:].strip().strip('"'))
    return sorted(paths)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _file_mode(path: Path) -> str:
    """A git-tree-style mode string ("100755" executable / "100644"
    regular) - a property of the file's OWN permission bits, stable
    across a commit (unlike tracked-vs-untracked status, which by
    definition changes the moment the file is committed - see
    `InventoryEntry.tracking_status`, deliberately kept OUT of the
    fingerprint payload for exactly that reason)."""
    return "100755" if os.access(path, os.X_OK) else "100644"


def _classify_with_size(rel_path: str, size_bytes: int) -> tuple[Classification, str]:
    classification, reason = classify_path(rel_path)
    if (
        classification not in ("secret_excluded", "temporary_excluded", "runtime_data_excluded")
        and size_bytes > LARGE_FILE_LIMIT_BYTES
    ):
        return (
            "large_file_excluded",
            f"{size_bytes} bytes exceeds the {LARGE_FILE_LIMIT_BYTES}-byte release limit",
        )
    return classification, reason


def build_release_inventory(repo_root: Path | None = None) -> ReleaseInventory:
    """Enumerates every tracked file (`git ls-files`) plus every
    untracked file (`git status --untracked-files=all`) - read-only,
    never touches the index - and classifies each one. An untracked file
    that would otherwise classify as release content is NOT silently
    included: its classification is still computed (and it DOES enter
    the fingerprint - Fase 11A section 5: "não presuma que todo untracked
    é efêmero"), but `requires_human_review` is set, since it is real,
    unreviewed content nobody has run `git add` on yet."""
    repo_root = repo_root or Path.cwd()
    entries: list[InventoryEntry] = []
    seen: set[str] = set()

    for rel_path in _tracked_files(repo_root):
        seen.add(rel_path)
        full_path = repo_root / rel_path
        if not full_path.is_file():
            # Tracked in git's index but missing from the working tree
            # (`rm` without `git rm`) - a real uncommitted deletion, not
            # part of the CURRENT intended payload either way.
            continue
        size = full_path.stat().st_size
        classification, reason = _classify_with_size(rel_path, size)
        entries.append(
            InventoryEntry(
                path=rel_path,
                file_mode=_file_mode(full_path),
                size_bytes=size,
                sha256=_sha256_file(full_path),
                classification=classification,
                reason=reason,
                tracking_status="tracked",
                requires_human_review=False,
            )
        )

    for rel_path in _untracked_files(repo_root):
        if rel_path in seen:
            continue
        full_path = repo_root / rel_path
        if full_path.is_dir() or not full_path.is_file():
            # git reports an untracked directory as a single path with a
            # trailing slash when none of its contents are tracked
            # either - walk it explicitly rather than hashing a directory.
            if full_path.is_dir():
                for nested in sorted(full_path.rglob("*")):
                    if not nested.is_file():
                        continue
                    nested_rel = str(nested.relative_to(repo_root)).replace("\\", "/")
                    if nested_rel in seen:
                        continue
                    seen.add(nested_rel)
                    size = nested.stat().st_size
                    classification, reason = _classify_with_size(nested_rel, size)
                    review = classification in INCLUDED_CLASSIFICATIONS
                    entries.append(
                        InventoryEntry(
                            path=nested_rel,
                            file_mode=_file_mode(nested),
                            size_bytes=size,
                            sha256=_sha256_file(nested),
                            classification=classification,
                            reason=reason,
                            tracking_status="untracked",
                            requires_human_review=review,
                        )
                    )
            continue
        seen.add(rel_path)
        size = full_path.stat().st_size
        classification, reason = _classify_with_size(rel_path, size)
        review = classification in INCLUDED_CLASSIFICATIONS
        entries.append(
            InventoryEntry(
                path=rel_path,
                file_mode=_file_mode(full_path),
                size_bytes=size,
                sha256=_sha256_file(full_path),
                classification=classification,
                reason=reason,
                tracking_status="untracked",
                requires_human_review=review,
            )
        )

    entries.sort(key=lambda e: e.path)
    fingerprint = compute_inventory_fingerprint(entries)
    return ReleaseInventory(
        schema_version=INVENTORY_SCHEMA_VERSION, entries=tuple(entries), fingerprint=fingerprint
    )


def compute_inventory_fingerprint(entries: list[InventoryEntry]) -> str:
    """Deterministic SHA-256 over the INTENDED release payload only
    (`INCLUDED_CLASSIFICATIONS`, minus `SELF_REFERENTIAL_EVIDENCE`),
    ordered by path. The payload is exactly: path, file_mode, size,
    sha256, classification, schema version - deliberately NOT
    `tracking_status` (tracked/untracked), since that is precisely the
    one thing committing a file changes, and section 8's own requirement
    is that content must NOT change just because it was committed.
    Never HEAD, a timestamp, a username, an absolute path, or dirty
    status either - those may be recorded as separate, non-deterministic
    metadata, never mixed into this digest."""
    digest = hashlib.sha256()
    digest.update(str(INVENTORY_SCHEMA_VERSION).encode("utf-8"))
    digest.update(b"\x00")
    for entry in sorted(entries, key=lambda e: e.path):
        if entry.classification not in INCLUDED_CLASSIFICATIONS:
            continue
        if entry.path in SELF_REFERENTIAL_EVIDENCE:
            continue
        digest.update(entry.path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(entry.file_mode.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(entry.size_bytes).encode("utf-8"))
        digest.update(b"\x00")
        digest.update(entry.sha256.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(entry.classification.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()
