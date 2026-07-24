"""SHA-256 checksums for raw data files.

Used both at acquisition time (record what was downloaded) and at
verification time (detect drift / corruption / silent replacement).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def compute_sha256(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file, streaming to avoid loading
    large files fully into memory.

    Raises:
        FileNotFoundError: if `path` does not exist or is not a file.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Cannot checksum '{path}': not a file or does not exist.")

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: Path, expected_sha256: str) -> bool:
    """Return True if `path`'s current SHA-256 matches `expected_sha256`
    (case-insensitive hex comparison).
    """
    actual = compute_sha256(path)
    return actual.lower() == expected_sha256.strip().lower()
