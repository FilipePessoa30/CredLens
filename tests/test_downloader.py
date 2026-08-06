"""Tests for credlens.data.downloader: HTTP mocked via `responses`."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
import requests
import responses

from credlens.data.downloader import (
    DestinationExistsError,
    DownloadError,
    PathTraversalError,
    download_file,
    extract_zip_safely,
    write_bytes_atomically,
)

FIXTURE_URL = "https://example.invalid/fixture.csv"


@responses.activate
def test_download_file_success_writes_content_and_checksum(tmp_path: Path) -> None:
    responses.add(
        responses.GET, FIXTURE_URL, body=b"a,b\n1,2\n", status=200, content_type="text/csv"
    )
    dest_dir = tmp_path / "raw"

    result = download_file(FIXTURE_URL, dest_dir, "fixture.csv", source_id="fixture")

    assert (dest_dir / "fixture.csv").read_bytes() == b"a,b\n1,2\n"
    assert result.size_bytes == len(b"a,b\n1,2\n")
    assert len(result.sha256) == 64
    assert result.source_id == "fixture"
    assert result.content_type == "text/csv"


@responses.activate
def test_download_file_refuses_overwrite_without_force(tmp_path: Path) -> None:
    responses.add(responses.GET, FIXTURE_URL, body=b"content", status=200)
    (tmp_path / "fixture.csv").write_text("pre-existing")

    with pytest.raises(DestinationExistsError):
        download_file(FIXTURE_URL, tmp_path, "fixture.csv", source_id="fixture")

    assert (tmp_path / "fixture.csv").read_text() == "pre-existing"


@responses.activate
def test_download_file_force_overwrites(tmp_path: Path) -> None:
    (tmp_path / "fixture.csv").write_text("stale content")
    responses.add(responses.GET, FIXTURE_URL, body=b"fresh content", status=200)

    result = download_file(FIXTURE_URL, tmp_path, "fixture.csv", source_id="fixture", force=True)

    assert (tmp_path / "fixture.csv").read_bytes() == b"fresh content"
    assert result.size_bytes == len(b"fresh content")


@responses.activate
def test_download_file_client_error_is_not_retried(tmp_path: Path) -> None:
    responses.add(responses.GET, FIXTURE_URL, status=404)

    with pytest.raises(DownloadError, match="HTTP 404"):
        download_file(FIXTURE_URL, tmp_path, "fixture.csv", source_id="fixture", max_retries=3)

    # Only one request should have been made - 4xx is not retried.
    assert len(responses.calls) == 1
    assert not (tmp_path / "fixture.csv").exists()


@responses.activate
def test_download_file_retries_on_429_then_succeeds(tmp_path: Path) -> None:
    # Fase 11D - unlike a genuine 4xx (a wrong/missing resource, never
    # fixed by retrying), 429 is HTTP's own standard signal that a later
    # attempt can legitimately succeed (e.g. a source rate-limiting a
    # shared IP range, such as a CI provider's runners) - confirmed as a
    # real gap: this downloader previously treated 429 identically to a
    # permanent 404/403 and never retried it.
    responses.add(responses.GET, FIXTURE_URL, status=429)
    responses.add(responses.GET, FIXTURE_URL, body=b"recovered after rate limit", status=200)

    download_file(
        FIXTURE_URL,
        tmp_path,
        "fixture.csv",
        source_id="fixture",
        max_retries=2,
        retry_backoff_seconds=0,
    )

    assert len(responses.calls) == 2
    assert (tmp_path / "fixture.csv").read_bytes() == b"recovered after rate limit"


@responses.activate
def test_download_file_honors_numeric_retry_after_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr("credlens.data.downloader.time.sleep", sleep_calls.append)
    responses.add(responses.GET, FIXTURE_URL, status=429, headers={"Retry-After": "5"})
    responses.add(responses.GET, FIXTURE_URL, body=b"ok", status=200)

    download_file(
        FIXTURE_URL,
        tmp_path,
        "fixture.csv",
        source_id="fixture",
        max_retries=2,
    )

    assert sleep_calls == [5.0]


@responses.activate
def test_download_file_429_without_retry_after_uses_default_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr("credlens.data.downloader.time.sleep", sleep_calls.append)
    responses.add(responses.GET, FIXTURE_URL, status=429)
    responses.add(responses.GET, FIXTURE_URL, body=b"ok", status=200)

    download_file(
        FIXTURE_URL,
        tmp_path,
        "fixture.csv",
        source_id="fixture",
        max_retries=2,
        retry_backoff_seconds=3,
    )

    assert sleep_calls == [3.0]


@responses.activate
def test_download_file_429_exhausts_retries_and_raises(tmp_path: Path) -> None:
    responses.add(responses.GET, FIXTURE_URL, status=429)
    responses.add(responses.GET, FIXTURE_URL, status=429)

    with pytest.raises(DownloadError, match="after 2 attempt"):
        download_file(
            FIXTURE_URL,
            tmp_path,
            "fixture.csv",
            source_id="fixture",
            max_retries=2,
            retry_backoff_seconds=0,
        )

    assert len(responses.calls) == 2
    assert not (tmp_path / "fixture.csv").exists()


@responses.activate
def test_download_file_retries_on_server_error_then_succeeds(tmp_path: Path) -> None:
    responses.add(responses.GET, FIXTURE_URL, status=503)
    responses.add(responses.GET, FIXTURE_URL, body=b"recovered", status=200)

    result = download_file(
        FIXTURE_URL,
        tmp_path,
        "fixture.csv",
        source_id="fixture",
        max_retries=3,
        retry_backoff_seconds=0,
    )

    assert len(responses.calls) == 2
    assert (tmp_path / "fixture.csv").read_bytes() == b"recovered"
    assert result.size_bytes == len(b"recovered")


@responses.activate
def test_download_file_gives_up_after_max_retries(tmp_path: Path) -> None:
    responses.add(responses.GET, FIXTURE_URL, status=503)
    responses.add(responses.GET, FIXTURE_URL, status=503)

    with pytest.raises(DownloadError, match="after 2 attempt"):
        download_file(
            FIXTURE_URL,
            tmp_path,
            "fixture.csv",
            source_id="fixture",
            max_retries=2,
            retry_backoff_seconds=0,
        )

    assert len(responses.calls) == 2
    assert not (tmp_path / "fixture.csv").exists()


@responses.activate
def test_download_file_times_out_and_is_retried(tmp_path: Path) -> None:
    responses.add(responses.GET, FIXTURE_URL, body=requests.exceptions.Timeout("simulated timeout"))
    responses.add(responses.GET, FIXTURE_URL, body=b"ok after timeout", status=200)

    result = download_file(
        FIXTURE_URL,
        tmp_path,
        "fixture.csv",
        source_id="fixture",
        max_retries=2,
        retry_backoff_seconds=0,
    )

    assert result.size_bytes == len(b"ok after timeout")


@responses.activate
def test_download_file_never_leaves_a_partial_file_on_failure(tmp_path: Path) -> None:
    responses.add(responses.GET, FIXTURE_URL, status=500)
    dest_dir = tmp_path / "raw"

    with pytest.raises(DownloadError):
        download_file(
            FIXTURE_URL,
            dest_dir,
            "fixture.csv",
            source_id="fixture",
            max_retries=1,
            retry_backoff_seconds=0,
        )

    assert not (dest_dir / "fixture.csv").exists()
    # No stray .part temp files left behind either.
    assert list(dest_dir.glob("*.part")) == []


@responses.activate
def test_download_file_rejects_unexpected_content_type(tmp_path: Path) -> None:
    responses.add(
        responses.GET, FIXTURE_URL, body=b"<html>not csv</html>", content_type="text/html"
    )

    with pytest.raises(DownloadError, match="Unexpected Content-Type"):
        download_file(
            FIXTURE_URL,
            tmp_path,
            "fixture.csv",
            source_id="fixture",
            expected_content_types=("text/csv",),
        )


def test_download_file_rejects_path_traversal_filename(tmp_path: Path) -> None:
    # A filename crafted to escape the intended destination directory
    # (e.g. from a tampered registry entry) is refused before any network
    # call or filesystem write happens.
    with pytest.raises(PathTraversalError):
        write_bytes_atomically(b"data", tmp_path, "../../etc/passwd")


def test_write_bytes_atomically_writes_and_respects_force(tmp_path: Path) -> None:
    destination = write_bytes_atomically(b'{"a": 1}', tmp_path, "series.json")
    assert destination.read_bytes() == b'{"a": 1}'

    with pytest.raises(DestinationExistsError):
        write_bytes_atomically(b'{"a": 2}', tmp_path, "series.json")

    write_bytes_atomically(b'{"a": 2}', tmp_path, "series.json", force=True)
    assert destination.read_bytes() == b'{"a": 2}'


def test_extract_zip_safely_extracts_all_members(tmp_path: Path) -> None:
    archive_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("one.txt", "first file")
        archive.writestr("two.txt", "second file")

    destination_dir = tmp_path / "extracted"
    extracted = extract_zip_safely(archive_path, destination_dir)

    names = {path.name for path in extracted}
    assert names == {"one.txt", "two.txt"}
    assert (destination_dir / "one.txt").read_text() == "first file"
    assert (destination_dir / "two.txt").read_text() == "second file"


def test_extract_zip_safely_rejects_path_traversal_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../../escaped.txt", "should not escape")

    destination_dir = tmp_path / "extracted"
    with pytest.raises(PathTraversalError):
        extract_zip_safely(archive_path, destination_dir)


def test_extract_zip_safely_refuses_overwrite_without_force(tmp_path: Path) -> None:
    archive_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("one.txt", "first version")

    destination_dir = tmp_path / "extracted"
    extract_zip_safely(archive_path, destination_dir)

    with pytest.raises(DestinationExistsError):
        extract_zip_safely(archive_path, destination_dir)
