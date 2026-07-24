"""Tests for credlens.data.checksums."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from credlens.data.checksums import compute_sha256, verify_sha256


def test_compute_sha256_matches_hashlib(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_bytes(b"credlens phase 2 fixture content")

    expected = hashlib.sha256(b"credlens phase 2 fixture content").hexdigest()
    assert compute_sha256(file_path) == expected


def test_compute_sha256_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        compute_sha256(tmp_path / "does_not_exist.bin")


def test_compute_sha256_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        compute_sha256(tmp_path)


def test_verify_sha256_accepts_matching_hash_case_insensitively(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.bin"
    file_path.write_bytes(b"some bytes")
    digest = compute_sha256(file_path)

    assert verify_sha256(file_path, digest.upper()) is True
    assert verify_sha256(file_path, f"  {digest}  ") is True


def test_verify_sha256_rejects_mismatched_hash(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.bin"
    file_path.write_bytes(b"original content")

    assert verify_sha256(file_path, "0" * 64) is False


def test_verify_sha256_detects_file_alteration(tmp_path: Path) -> None:
    file_path = tmp_path / "mutable.bin"
    file_path.write_bytes(b"version one")
    original_digest = compute_sha256(file_path)

    file_path.write_bytes(b"version two - altered")

    assert verify_sha256(file_path, original_digest) is False
