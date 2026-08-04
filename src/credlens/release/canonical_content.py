"""Canonical, cross-platform representations of a working-tree file's
content and mode - shared by `source_snapshot` and `inventory`, both of
which fingerprint on-disk files and must agree with git's own storage
policy (Fase 11B section 8) rather than whatever a particular OS
checkout happens to produce.

Two concrete, CONFIRMED bugs motivated this module (verified on this
machine, not merely theoretical):

1. CRLF/LF: `.gitattributes` sets `* text=auto eol=lf`, so git stores
   every text file with LF endings regardless of platform - but this
   Windows working tree (`core.autocrlf=true`) holds CRLF on disk.
   `src/credlens/cli.py` hashed to two different SHA-256 digests
   depending on whether the raw disk bytes (CRLF) or git's own blob
   content (LF) were read, for the exact same commit.

2. Executable bit: this repo's local `.git/config` has
   `core.filemode=false` and `git ls-files -s` reports "100644" for
   EVERY tracked file (no "100755" entries exist at all) - but
   `os.access(path, os.X_OK)` returns True for essentially any
   readable file on Windows (Windows has no POSIX execute bit), so the
   old `_file_mode()` reported "100755" for every single file on this
   machine while a Linux checkout of the same commit would (correctly)
   report "100644".

Both bugs share the same shape: reading a platform-dependent OS-level
observation instead of asking git (or git's own stated policy) what it
actually stores. The fix in both cases is to canonicalize to what git
itself would record, not to the raw filesystem's answer.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Extensions this repo's own `.gitattributes` marks binary/-text (never
# line-ending-converted by git, so raw bytes ARE already the canonical
# content) - kept in sync with `.gitattributes` by hand, since resolving
# git's actual attribute for every one of the ~675 release files would
# mean one `git check-attr` subprocess call per file.
_BINARY_EXTENSIONS = frozenset(
    {
        ".csv",
        ".parquet",
        ".duckdb",
        ".pbix",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".db",
        ".sqlite",
        ".zip",
        ".whl",
    }
)

# The mode git assigns to a newly-added file under this repo's own
# `core.filemode=false` (see module docstring): never derived from the
# observing OS's executable-bit semantics.
DEFAULT_FILE_MODE = "100644"


def canonicalize_content(rel_path: str, raw_bytes: bytes) -> bytes:
    """Returns `raw_bytes` as git would store it as a blob, given this
    repo's own `.gitattributes` (`* text=auto eol=lf` plus explicit
    binary exceptions): CRLF and lone-CR normalized to LF for text
    files, unchanged for binary ones. Content actually containing a
    NUL byte is treated as binary regardless of extension - the same
    heuristic git itself uses to auto-detect binary content."""
    suffix = Path(rel_path).suffix.lower()
    if suffix in _BINARY_EXTENSIONS or b"\x00" in raw_bytes:
        return raw_bytes
    return raw_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def git_tracked_file_modes(repo_root: Path) -> dict[str, str]:
    """path -> git's own index mode ("100644" / "100755" / "120000"
    symlink) for every TRACKED file, read straight from `git ls-files
    -s` - the one source of truth unaffected by `core.filemode` or the
    observing OS's own executable-bit semantics. Paths use forward
    slashes, matching `git ls-files`'s own output on every platform."""
    result = subprocess.run(
        ["git", "ls-files", "-s"], cwd=repo_root, capture_output=True, text=True, check=True
    )
    modes: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line:
            continue
        meta, _tab, path = line.partition("\t")
        modes[path] = meta.split()[0]
    return modes
