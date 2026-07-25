"""Parquet output with atomic staging -> promotion.

A run is written entirely to a temporary staging directory first,
validated, and only "promoted" (renamed) into its final
data/synthetic/<generation_run_id>/ location once validation succeeds -
so a failed or interrupted run never leaves partial artifacts in the
directory a consumer would actually read from. See
docs/synthetic_generation_implementation.md "Validation and atomicity".
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd


class PathSafetyError(Exception):
    """A resolved output path would escape its intended base directory."""


def resolve_within_directory(directory: Path, name: str) -> Path:
    """Mirrors credlens.data.downloader._resolve_within_directory's
    approach: resolve `directory` independently of `name`, then verify
    the joined result stays inside it - catches a run_id containing
    traversal sequences (e.g. '../../etc')."""
    base = directory.resolve()
    candidate = (base / name).resolve()
    if candidate != base and base not in candidate.parents:
        raise PathSafetyError(
            f"Refusing to write '{name}' outside of '{base}': resolved to '{candidate}'."
        )
    return candidate


def write_operational_tables(tables: dict[str, pd.DataFrame], target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(target_dir / f"{name}.parquet", index=False)


def write_truth_tables(tables: dict[str, pd.DataFrame], target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(target_dir / f"{name}.parquet", index=False)


def stage_directory(base_dir: Path) -> Path:
    """A private staging area under `base_dir` - never a system temp dir,
    so the final atomic move stays on the same filesystem (required for
    os.replace to be atomic)."""
    base_dir.mkdir(parents=True, exist_ok=True)
    staging_root = base_dir / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="run-", dir=staging_root))


def promote_staging(staging_path: Path, final_path: Path) -> None:
    """Atomically move a validated staging directory into place. If
    `final_path` already exists, the caller must have already confirmed
    `--force` was given and removed/renamed it - this function does not
    silently overwrite."""
    if final_path.exists():
        raise FileExistsError(f"Refusing to promote over existing path '{final_path}'.")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging_path, final_path)


def discard_staging(staging_path: Path) -> None:
    """Removes a staging directory after a failed run - never touches
    anything outside the .staging/ area it was created under."""
    if staging_path.exists():
        shutil.rmtree(staging_path)
