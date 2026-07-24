"""Tests for credlens.data.manifest: deterministic read/write/verify."""

from __future__ import annotations

from pathlib import Path

import pytest

from credlens.data.manifest import ManifestError, read_manifest, verify_manifest, write_manifest
from credlens.data.models import ManifestEntry


def _entry(source_id: str, relative_path: str, sha256: str = "a" * 64) -> ManifestEntry:
    return ManifestEntry(
        source_id=source_id,
        relative_path=relative_path,
        filename=Path(relative_path).name,
        size_bytes=123,
        sha256=sha256,
        retrieved_at_utc="2026-01-01T00:00:00+00:00",
        url="https://example.invalid/file",
        format="csv",
        num_rows=10,
        num_columns=3,
        verification_status="unverified",
        source_version_or_date="2020",
        license="CC BY 4.0",
        notes="",
    )


def test_write_and_read_manifest_round_trips(tmp_path: Path) -> None:
    entries = [_entry("source-b", "data/raw/b/file.csv"), _entry("source-a", "data/raw/a/file.csv")]
    manifest_path = tmp_path / "file_manifest.csv"

    write_manifest(entries, manifest_path)
    read_back = read_manifest(manifest_path)

    assert len(read_back) == 2
    assert {e.source_id for e in read_back} == {"source-a", "source-b"}


def test_write_manifest_orders_deterministically_by_source_id_then_path(tmp_path: Path) -> None:
    entries = [
        _entry("zeta", "data/raw/zeta/file.csv"),
        _entry("alpha", "data/raw/alpha/z.csv"),
        _entry("alpha", "data/raw/alpha/a.csv"),
    ]
    manifest_path = tmp_path / "file_manifest.csv"

    write_manifest(entries, manifest_path)
    read_back = read_manifest(manifest_path)

    assert [(e.source_id, e.relative_path) for e in read_back] == [
        ("alpha", "data/raw/alpha/a.csv"),
        ("alpha", "data/raw/alpha/z.csv"),
        ("zeta", "data/raw/zeta/file.csv"),
    ]


def test_write_manifest_is_reproducible_byte_for_byte(tmp_path: Path) -> None:
    entries = [_entry("source-a", "data/raw/a/file.csv"), _entry("source-b", "data/raw/b/file.csv")]
    path_one = tmp_path / "one.csv"
    path_two = tmp_path / "two.csv"

    write_manifest(entries, path_one)
    write_manifest(list(reversed(entries)), path_two)  # different input order

    assert path_one.read_text(encoding="utf-8") == path_two.read_text(encoding="utf-8")


def test_read_manifest_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="not found"):
        read_manifest(tmp_path / "does_not_exist.csv")


def test_read_manifest_malformed_row_raises(tmp_path: Path) -> None:
    manifest_path = tmp_path / "broken.csv"
    manifest_path.write_text(
        "source_id,relative_path,filename,size_bytes,sha256,retrieved_at_utc,url,format,"
        "num_rows,num_columns,verification_status,source_version_or_date,license,notes\n"
        "source-a,data/raw/a/file.csv,file.csv,NOT_A_NUMBER,abc,2026-01-01,https://x,csv,,,"
        "unverified,2020,CC BY 4.0,\n",
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="line 2"):
        read_manifest(manifest_path)


def test_verify_manifest_reports_ok_for_untouched_file(tmp_path: Path) -> None:
    data_file = tmp_path / "data" / "raw" / "a" / "file.csv"
    data_file.parent.mkdir(parents=True)
    data_file.write_bytes(b"hello world")

    from credlens.data.checksums import compute_sha256

    entry = _entry("source-a", "data/raw/a/file.csv", sha256=compute_sha256(data_file))
    manifest_path = tmp_path / "file_manifest.csv"
    write_manifest([entry], manifest_path)

    results = verify_manifest(manifest_path, tmp_path)

    assert results == [(entry, "OK")]


def test_verify_manifest_detects_altered_file(tmp_path: Path) -> None:
    data_file = tmp_path / "data" / "raw" / "a" / "file.csv"
    data_file.parent.mkdir(parents=True)
    data_file.write_bytes(b"original content")

    from credlens.data.checksums import compute_sha256

    entry = _entry("source-a", "data/raw/a/file.csv", sha256=compute_sha256(data_file))
    manifest_path = tmp_path / "file_manifest.csv"
    write_manifest([entry], manifest_path)

    data_file.write_bytes(b"tampered content")
    results = verify_manifest(manifest_path, tmp_path)

    assert results == [(entry, "MISMATCH")]


def test_verify_manifest_detects_missing_file(tmp_path: Path) -> None:
    entry = _entry("source-a", "data/raw/a/never_downloaded.csv")
    manifest_path = tmp_path / "file_manifest.csv"
    write_manifest([entry], manifest_path)

    results = verify_manifest(manifest_path, tmp_path)

    assert results == [(entry, "MISSING")]


def test_manifest_uses_relative_paths_not_absolute(tmp_path: Path) -> None:
    entry = _entry("source-a", "data/raw/a/file.csv")
    manifest_path = tmp_path / "file_manifest.csv"
    write_manifest([entry], manifest_path)

    content = manifest_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in content
    assert "data/raw/a/file.csv" in content
