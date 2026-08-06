"""Idempotent, reproducible HTTP(S) file downloader for raw data acquisition.

Design goals (see docs/dataset_selection.md and the Phase 2 brief this
module implements): explicit timeouts, bounded retries with backoff, no
partial files ever left at the destination, no silent overwrite, no
credentials in logs, and a verifiable record (checksum, final URL,
retrieval timestamp) of exactly what was fetched.
"""

from __future__ import annotations

import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import requests

from credlens.data.checksums import compute_sha256
from credlens.data.models import DownloadResult
from credlens.logging_config import get_logger

logger = get_logger("data.downloader")

DEFAULT_USER_AGENT = (
    "credlens-data-acquisition/0.1 (+https://github.com/FilipePessoa30/CredLens; portfolio project)"
)
_CHUNK_SIZE = 256 * 1024  # 256 KiB


class DownloadError(Exception):
    """A download could not be completed, or was refused for safety reasons."""


class RateLimitedError(DownloadError):
    """The server responded 429 Too Many Requests - unlike a genuine 4xx
    client error (a wrong/missing resource, which no retry will ever
    fix), a 429 is HTTP's own standard way of saying "you legitimately
    can succeed, just not yet" (RFC 6585) - the one 4xx status this
    downloader retries, honoring a numeric `Retry-After` header if the
    server sent one."""

    def __init__(self, message: str, *, retry_after_seconds: float | None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class DestinationExistsError(DownloadError):
    """The destination file already exists and `force` was not set."""


class PathTraversalError(DownloadError):
    """A resolved file path would escape its intended directory."""


def _resolve_within_directory(directory: Path, filename: str) -> Path:
    """Join `filename` onto `directory` and verify the result stays inside it.

    `directory` is resolved first, independently of `filename`, so this
    genuinely catches a `filename` containing traversal sequences (e.g.
    `"../../etc/passwd"`) - unlike resolving the already-joined path and
    then comparing it to its own parent, which can never detect anything
    (the comparison would trivially always pass).
    """
    base = directory.resolve()
    candidate = (base / filename).resolve()
    if candidate != base and base not in candidate.parents:
        raise PathTraversalError(
            f"Refusing to write '{filename}' outside of '{base}': resolved to '{candidate}'."
        )
    return candidate


def _redact_url(url: str) -> str:
    """Strip a query string before logging, in case a URL ever carries a token."""
    return url.split("?")[0]


def _parse_retry_after(raw_value: str | None) -> float | None:
    """RFC 9110 section 10.2.3 defines `Retry-After` as EITHER an integer number
    of seconds OR an HTTP-date - only the numeric-seconds form (what
    every server this project talks to actually sends) is parsed; an
    HTTP-date or a missing/malformed header falls back to this
    downloader's own fixed backoff instead of failing the download."""
    if raw_value is None:
        return None
    try:
        return max(0.0, float(raw_value))
    except ValueError:
        return None


def download_file(
    url: str,
    destination_dir: Path,
    filename: str,
    *,
    source_id: str,
    timeout_seconds: float = 30.0,
    max_retries: int = 3,
    retry_backoff_seconds: float = 2.0,
    user_agent: str = DEFAULT_USER_AGENT,
    expected_content_types: tuple[str, ...] | None = None,
    force: bool = False,
) -> DownloadResult:
    """Download `url` into `destination_dir/filename`, atomically, with retries.

    Raises:
        PathTraversalError: `filename` resolves outside `destination_dir`.
        DestinationExistsError: destination exists and `force` is False.
        DownloadError: the request failed after retries, or the response's
            content type did not match `expected_content_types`.
    """
    destination = _resolve_within_directory(destination_dir, filename)

    if destination.exists() and not force:
        raise DestinationExistsError(
            f"'{destination.name}' already exists at '{destination.parent}'. "
            "Pass --force to re-download and overwrite it."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": user_agent}
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            return _attempt_download(
                url,
                destination,
                source_id=source_id,
                headers=headers,
                timeout_seconds=timeout_seconds,
                expected_content_types=expected_content_types,
                attempt=attempt,
            )
        except RateLimitedError as exc:
            last_error = exc
            wait_seconds = (
                exc.retry_after_seconds
                if exc.retry_after_seconds is not None
                else retry_backoff_seconds * attempt
            )
            logger.warning(
                "Attempt %d/%d rate-limited (429) for %s - waiting %.1fs before retrying: %s",
                attempt,
                max_retries,
                _redact_url(url),
                wait_seconds,
                exc,
            )
            if attempt < max_retries:
                time.sleep(wait_seconds)
        except DownloadError:
            raise
        except requests.RequestException as exc:
            last_error = exc
            logger.warning(
                "Attempt %d/%d failed for %s: %s",
                attempt,
                max_retries,
                _redact_url(url),
                exc,
            )
            if attempt < max_retries:
                time.sleep(retry_backoff_seconds * attempt)

    raise DownloadError(
        f"Failed to download {_redact_url(url)} after {max_retries} attempt(s): {last_error}"
    ) from last_error


def _attempt_download(
    url: str,
    destination: Path,
    *,
    source_id: str,
    headers: dict[str, str],
    timeout_seconds: float,
    expected_content_types: tuple[str, ...] | None,
    attempt: int,
) -> DownloadResult:
    with requests.get(url, headers=headers, timeout=timeout_seconds, stream=True) as response:
        if response.status_code == 429:
            raise RateLimitedError(
                f"Source rate-limited the request: HTTP 429 for {_redact_url(url)}.",
                retry_after_seconds=_parse_retry_after(response.headers.get("Retry-After")),
            )
        if 400 <= response.status_code < 500:
            raise DownloadError(
                f"Source unavailable or refused the request: HTTP {response.status_code} "
                f"for {_redact_url(url)}. This is not retried (client error)."
            )
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
        if expected_content_types and content_type not in expected_content_types:
            raise DownloadError(
                f"Unexpected Content-Type '{content_type}' for {_redact_url(url)} "
                f"(expected one of {expected_content_types})."
            )

        _stream_to_file_atomically(response, destination)

        sha256 = compute_sha256(destination)
        size_bytes = destination.stat().st_size
        retrieved_at = datetime.now(UTC).isoformat()

        logger.info(
            "Downloaded %s (%d bytes, sha256=%s...) after %d attempt(s).",
            destination.name,
            size_bytes,
            sha256[:12],
            attempt,
        )

        return DownloadResult(
            source_id=source_id,
            path=destination,
            url=url,
            final_url=response.url or url,
            size_bytes=size_bytes,
            sha256=sha256,
            retrieved_at_utc=retrieved_at,
            content_type=content_type or None,
        )


def _stream_to_file_atomically(response: requests.Response, destination: Path) -> None:
    """Write the response body to a temp file, then rename atomically.

    A failure (network error, disk full, interrupt) partway through never
    leaves a partial file at `destination` - either the temp file is
    cleaned up, or the rename has already completed.
    """
    fd, tmp_name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".part"
    )
    tmp_path = Path(tmp_name)
    try:
        with open(fd, "wb") as tmp_file:
            for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                if chunk:
                    tmp_file.write(chunk)
        tmp_path.replace(destination)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def write_bytes_atomically(
    data: bytes, destination_dir: Path, filename: str, *, force: bool = False
) -> Path:
    """Write `data` into `destination_dir/filename` atomically (temp file + rename).

    Used for sources whose content already arrived in memory (e.g. a BCB
    SGS API response) rather than being streamed from an HTTP response.
    Returns the resolved destination path.

    Raises:
        PathTraversalError: `filename` resolves outside `destination_dir`.
        DestinationExistsError: destination exists and `force` is False.
    """
    destination = _resolve_within_directory(destination_dir, filename)
    if destination.exists() and not force:
        raise DestinationExistsError(
            f"'{destination.name}' already exists at '{destination.parent}'. "
            "Pass --force to overwrite it."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".part"
    )
    tmp_path = Path(tmp_name)
    try:
        with open(fd, "wb") as tmp_file:
            tmp_file.write(data)
        tmp_path.replace(destination)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    return destination


def extract_zip_safely(
    archive_path: Path, destination_dir: Path, *, force: bool = False
) -> list[Path]:
    """Extract every member of a zip archive into `destination_dir`.

    Each member's resolved destination is checked to stay within
    `destination_dir` before extraction (defense against a "zip slip"
    path-traversal attack via a crafted archive entry name). This
    decompresses the archive's own already-downloaded bytes - it does not
    alter their content, so the archive itself remains the authoritative
    raw artifact (see docs/data_sources.md).

    Raises:
        PathTraversalError: a member's path would escape `destination_dir`.
        DestinationExistsError: a member's target file exists and `force`
            is False.
    """
    destination_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []

    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            member_path = _resolve_within_directory(destination_dir, member.filename)
            if member_path.exists() and not force:
                raise DestinationExistsError(
                    f"'{member_path.name}' already exists at '{member_path.parent}'. "
                    "Pass --force to re-extract and overwrite it."
                )
            member_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, open(member_path, "wb") as target:
                target.write(source.read())
            extracted.append(member_path)
            logger.info("Extracted %s from %s.", member_path.name, archive_path.name)

    return extracted
