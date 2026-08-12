"""Canonical release-asset checksum manifest (Fase 12).

Root cause of the Fase 11F "obsolete SHA256SUMS" finding: `reports/
release/SHA256SUMS` was introduced in a single commit (Fase 11A,
`adf7702`) via a manual, one-off `sha256sum`-style invocation over five
explicit files, and never touched again - it has no `source_snapshot_
fingerprint` field the way `coverage_snapshot.json`/`release_manifest.
json` do, so its own staleness is invisible to everything else. It was
never wired to any CLI command, any `credlens release validate` check,
or any generator - `git log --follow` on the file shows exactly one
commit in its entire history. Every one of the files it covers
(most visibly `release_manifest.json`, regenerated dozens of times
across Fase 11B-11F) kept evolving underneath it, so it silently drifted
correct-at-creation-time to stale-by-release-time. It was never
detected because nothing ever re-derived or re-checked it - not because
any check was fooled.

(The `v1.0.0rc2` Pre-Release's own published SHA256SUMS additionally
covered `docs/recruiter_brief.md`/`.pt-BR.md` - those files were
removed from the repository in Fase 12 (this project is presented as a
portfolio item, not audience-specific interview/recruiter collateral),
so `CANONICAL_RELEASE_ASSETS` below no longer references them. The
already-published `v1.0.0rc2` Release and its own attached assets are
immutable and were NOT altered to match - see Fase 12 section 3.)

This module makes checksum generation and verification first-class,
deterministic operations, closing that gap prospectively:

- `write_release_checksums` (re)generates SHA256SUMS from the CURRENT
  on-disk content of exactly `CANONICAL_RELEASE_ASSETS` - a fixed,
  explicit, non-wildcard tuple, never a directory scan - in that fixed
  declared order (not filesystem/OS enumeration order, so output is
  byte-identical on Windows and Linux given the same input). It must be
  called LAST, after `release_manifest.json`/`sbom.cyclonedx.json`/
  `license_inventory.json` have already been (re)generated - this
  avoids the circular dependency a `credlens release manifest` caller
  might otherwise create (release_manifest.json's own content never
  depends on SHA256SUMS, but SHA256SUMS's content depends on release_
  manifest.json's already-final bytes). SHA256SUMS never hashes itself.
- `verify_release_checksums` re-derives the same canonical set FRESH
  from disk and diffs it against what the committed file actually
  declares - never trusts the file's own claim that it is up to date.
  Missing asset, undeclared/unexpected entry, and stale/incorrect hash
  are reported as distinct failure modes.

Hashes are computed over `canonicalize_content`'s output (CRLF/CR
normalized to LF for text files, matching this repo's own
`.gitattributes`), never raw bytes - the first real PR built on this
module (Fase 12) failed exactly this way in real CI: hashes generated
on a Windows checkout (where these JSON files carry CRLF) didn't match
the same commit checked out fresh on the Linux CI runner (where
`.gitattributes`' `eol=lf` normalizes them to LF), for all three
canonical assets at once. `credlens.release.source_snapshot` already
solved this identical cross-platform problem for the source fingerprint
- this module reuses that same solution rather than re-inventing it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from credlens.release.canonical_content import canonicalize_content


class ChecksumError(Exception):
    """Raised when checksum generation cannot proceed."""


# Fixed, explicit, non-wildcard set - the release-asset contract
# (Fase 12 section 7). This is the ONLY place that declares which files
# SHA256SUMS covers; both the generator and the validator import it, so
# they can never silently diverge from each other.
CANONICAL_RELEASE_ASSETS: tuple[str, ...] = (
    "reports/release/sbom.cyclonedx.json",
    "reports/release/release_manifest.json",
    "reports/release/license_inventory.json",
)

CHECKSUMS_FILENAME = "SHA256SUMS"


def _checksums_path(repo_root: Path) -> Path:
    return repo_root / "reports" / "release" / CHECKSUMS_FILENAME


def _sha256_of(rel_path: str, path: Path) -> str:
    content = canonicalize_content(rel_path, path.read_bytes())
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class ChecksumEntry:
    path: str
    sha256: str


def compute_canonical_checksums(repo_root: Path) -> list[ChecksumEntry]:
    """Recomputes SHA-256 for exactly `CANONICAL_RELEASE_ASSETS`, in
    that declared order. Raises `ChecksumError` if any canonical asset
    is missing - a checksums file is never generated for a partial
    asset set."""
    missing = [rel for rel in CANONICAL_RELEASE_ASSETS if not (repo_root / rel).is_file()]
    if missing:
        raise ChecksumError(
            f"Missing canonical release asset(s), cannot compute checksums: {missing}"
        )
    return [
        ChecksumEntry(path=rel, sha256=_sha256_of(rel, repo_root / rel))
        for rel in CANONICAL_RELEASE_ASSETS
    ]


def render_checksums_file(entries: list[ChecksumEntry]) -> str:
    """`sha256sum`-compatible format ('<hash>  <path>', two spaces, LF
    line endings regardless of platform) - deterministic byte-for-byte
    output given the same input, independent of OS/filesystem."""
    return "".join(f"{e.sha256}  {e.path}\n" for e in entries)


def write_release_checksums(repo_root: Path | None = None) -> Path:
    """Generates SHA256SUMS LAST, from the current on-disk content of
    the canonical release assets. Callers are responsible for
    regenerating release_manifest.json/sbom.cyclonedx.json/license_
    inventory.json FIRST - this function only ever reads them, it never
    triggers their regeneration, so there is no circular dependency."""
    repo_root = repo_root or Path.cwd()
    entries = compute_canonical_checksums(repo_root)
    path = _checksums_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_checksums_file(entries), encoding="utf-8", newline="\n")
    return path


@dataclass(frozen=True)
class ChecksumVerificationResult:
    status: str  # "pass" | "fail"
    detail: str
    missing_from_file: list[str] = field(default_factory=list)
    undeclared_in_file: list[str] = field(default_factory=list)
    stale_or_incorrect: list[str] = field(default_factory=list)
    missing_assets_on_disk: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "detail": self.detail,
            "missing_from_file": self.missing_from_file,
            "undeclared_in_file": self.undeclared_in_file,
            "stale_or_incorrect": self.stale_or_incorrect,
            "missing_assets_on_disk": self.missing_assets_on_disk,
        }


def _parse_checksums_file(text: str) -> dict[str, str]:
    declared: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # sha256sum format: "<64-hex-digest>  <path>" (two spaces) or
        # "<digest> *<path>" (single space + binary-mode marker) - this
        # module never writes the '*' form, but tolerates it on read.
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, path = parts
        declared[path.lstrip("*")] = digest.lower()
    return declared


def verify_release_checksums(repo_root: Path | None = None) -> ChecksumVerificationResult:
    """Re-derives the canonical checksum set FRESH from disk and diffs
    it against what the committed SHA256SUMS file actually declares -
    never trusts the file's own claim that it is up to date. Distinct
    failure modes are reported separately (missing asset vs. an
    undeclared/unexpected entry vs. a stale/incorrect hash) rather than
    collapsed into one opaque "mismatch"."""
    repo_root = repo_root or Path.cwd()
    path = _checksums_path(repo_root)
    if not path.is_file():
        return ChecksumVerificationResult("fail", f"No {CHECKSUMS_FILENAME} found at '{path}'.")

    declared = _parse_checksums_file(path.read_text(encoding="utf-8"))

    missing_assets_on_disk = [
        rel for rel in CANONICAL_RELEASE_ASSETS if not (repo_root / rel).is_file()
    ]
    if missing_assets_on_disk:
        return ChecksumVerificationResult(
            "fail",
            f"Canonical release asset(s) missing on disk: {missing_assets_on_disk}",
            missing_assets_on_disk=missing_assets_on_disk,
        )

    canonical_set = set(CANONICAL_RELEASE_ASSETS)
    declared_set = set(declared)
    missing_from_file = sorted(canonical_set - declared_set)
    undeclared_in_file = sorted(declared_set - canonical_set)

    stale_or_incorrect = [
        rel
        for rel in CANONICAL_RELEASE_ASSETS
        if rel in declared and declared[rel] != _sha256_of(rel, repo_root / rel)
    ]

    if missing_from_file or undeclared_in_file or stale_or_incorrect:
        problems = []
        if missing_from_file:
            problems.append(f"missing from file: {missing_from_file}")
        if undeclared_in_file:
            problems.append(f"undeclared/unexpected entries: {undeclared_in_file}")
        if stale_or_incorrect:
            problems.append(f"stale or incorrect hash: {stale_or_incorrect}")
        return ChecksumVerificationResult(
            "fail",
            f"{CHECKSUMS_FILENAME} is inconsistent with the current canonical release assets - "
            + "; ".join(problems),
            missing_from_file=missing_from_file,
            undeclared_in_file=undeclared_in_file,
            stale_or_incorrect=stale_or_incorrect,
        )

    return ChecksumVerificationResult(
        "pass",
        f"{CHECKSUMS_FILENAME} matches the current content of all "
        f"{len(CANONICAL_RELEASE_ASSETS)} canonical release assets.",
    )
