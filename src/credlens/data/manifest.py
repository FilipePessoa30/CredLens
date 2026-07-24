"""Deterministic manifest of acquired raw files (data/metadata/file_manifest.csv).

The manifest is the single source of truth for "what raw file exists,
where, with what hash, from what source." It is always reproducible: it
can be rebuilt by recomputing hashes over data/raw/, and re-verified by
re-hashing the files it references. Paths are always relative to the
repository root - no absolute, machine-specific paths and no user
information are ever written to it.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, fields
from pathlib import Path

from credlens.data.checksums import compute_sha256
from credlens.data.models import ManifestEntry

MANIFEST_COLUMNS = [f.name for f in fields(ManifestEntry)]


class ManifestError(Exception):
    """Raised for manifest read/write/validation failures."""


def write_manifest(entries: list[ManifestEntry], manifest_path: Path) -> None:
    """Write `entries` to `manifest_path` as CSV, sorted deterministically
    by (source_id, relative_path) so the file diffs cleanly across runs.
    """
    ordered = sorted(entries, key=lambda e: (e.source_id, e.relative_path))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        for entry in ordered:
            writer.writerow(asdict(entry))


def read_manifest(manifest_path: Path) -> list[ManifestEntry]:
    """Read `manifest_path` back into a list of `ManifestEntry`.

    Raises:
        ManifestError: the file is missing or a row is malformed.
    """
    if not manifest_path.is_file():
        raise ManifestError(f"Manifest not found at '{manifest_path}'.")

    entries: list[ManifestEntry] = []
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for line_num, row in enumerate(reader, start=2):
            try:
                entries.append(
                    ManifestEntry(
                        source_id=row["source_id"],
                        relative_path=row["relative_path"],
                        filename=row["filename"],
                        size_bytes=int(row["size_bytes"]),
                        sha256=row["sha256"],
                        retrieved_at_utc=row["retrieved_at_utc"],
                        url=row["url"],
                        format=row["format"],
                        num_rows=int(row["num_rows"]) if row["num_rows"] else None,
                        num_columns=int(row["num_columns"]) if row["num_columns"] else None,
                        verification_status=row["verification_status"],
                        source_version_or_date=row["source_version_or_date"],
                        license=row["license"],
                        notes=row["notes"],
                    )
                )
            except (KeyError, ValueError) as exc:
                raise ManifestError(f"Malformed manifest row at line {line_num}: {exc}") from exc

    return entries


def verify_manifest(manifest_path: Path, repository_root: Path) -> list[tuple[ManifestEntry, str]]:
    """Recompute each manifest entry's checksum against the file on disk.

    Returns a list of `(entry, status)` pairs where status is one of
    `"OK"`, `"MISMATCH"`, or `"MISSING"`. Does not raise on a
    mismatch/missing file - callers (e.g. the CLI) decide how to report it.
    """
    entries = read_manifest(manifest_path)
    results: list[tuple[ManifestEntry, str]] = []
    for entry in entries:
        file_path = repository_root / entry.relative_path
        if not file_path.is_file():
            results.append((entry, "MISSING"))
            continue
        actual = compute_sha256(file_path)
        results.append((entry, "OK" if actual.lower() == entry.sha256.lower() else "MISMATCH"))
    return results
