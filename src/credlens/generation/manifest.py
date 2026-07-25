"""Canonical hashing and the run manifest.

Canonical table hash procedure (docs/synthetic_generation_implementation.md
"Reproducibility"):
  1. Columns sorted alphabetically.
  2. Rows sorted by every column's value, left to right (a total,
     deterministic order regardless of the order rows were produced in).
  3. Every value rendered to a fixed string form (NaN/None -> the literal
     "\x00NULL\x00", floats formatted with repr() for full precision,
     everything else via str()).
  4. The resulting rows joined into one big canonical text blob, hashed
     with SHA-256.

This does NOT promise byte-identical Parquet files across pandas/pyarrow
versions (row-group layout, compression, etc. can differ) - only that
the same logical content hashes the same, which is the actual
reproducibility contract this phase asks for.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from credlens.generation.config import GenerationConfig

_NULL_SENTINEL = "\x00NULL\x00"


def _canonical_cell(value: Any) -> str:
    # float first (the hot path: almost every cell in a wide numeric table
    # is a float) - value != value is the standard fast NaN test, avoiding
    # a pd.isna() call per cell.
    if isinstance(value, float):
        return _NULL_SENTINEL if value != value else repr(value)
    if value is None:
        return _NULL_SENTINEL
    return str(value)


def canonical_table_hash(df: pd.DataFrame) -> str:
    if df.empty:
        columns_key = ",".join(sorted(df.columns.astype(str)))
        return hashlib.sha256(f"EMPTY:{columns_key}".encode()).hexdigest()

    ordered_columns = sorted(df.columns.astype(str))
    ordered = df[ordered_columns].astype(object)
    canonical_cells = ordered.map(_canonical_cell)
    # A plain Python loop over a single whole-array .astype(str), NOT
    # DataFrame.apply(..., axis=1) calling row.to_numpy(dtype=str) once per
    # row: apply(axis=1) builds one pandas Series per row, which profiled
    # (cProfile, sample scale) at ~6.7s of a ~34s run - the second-largest
    # hotspot found. IMPORTANT: the per-row .to_numpy(dtype=str) in the
    # original code has a real side effect this rewrite must reproduce -
    # numpy's fixed-width unicode cast silently strips a trailing NUL byte
    # from _NULL_SENTINEL ("\x00NULL\x00" -> "\x00NULL" once cast). Since
    # that stripping is applied uniformly by the ORIGINAL code too, it must
    # be preserved here as well (a single .astype(str) over the whole
    # array has the identical effect, just computed once instead of once
    # per row) - otherwise this "pure performance" rewrite would silently
    # change every hash containing a null value. Caught by re-running the
    # baseline smoke seed and comparing manifests before trusting this.
    row_strings = ["\x1f".join(row) for row in canonical_cells.to_numpy().astype(str).tolist()]
    sorted_rows = sorted(row_strings)
    blob = "\x1e".join(sorted_rows)
    header = ",".join(ordered_columns)
    return hashlib.sha256(f"{header}\x1d{blob}".encode()).hexdigest()


def canonical_config_hash(config: GenerationConfig) -> str:
    # exclude_none=True: an optional field a scenario doesn't set (e.g.
    # baseline never sets macro_shock) must not affect the config's own
    # hash just because the SCHEMA later grew a new optional field for a
    # different scenario's use - otherwise every existing scenario's
    # generation_run_id (and, through it, every id prefix) would silently
    # churn each time Phase 4B added a new, unrelated, unset config
    # section. A field a scenario DOES set (e.g. macroeconomic_stress's
    # macro_shock) still participates in the hash normally.
    payload = config.model_dump(mode="json", exclude_none=True)
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode()).hexdigest()


def canonical_run_hash(
    table_hashes: dict[str, str], config_hash: str, seed: int, scenario: str, scale: str
) -> str:
    parts = [f"scenario={scenario}", f"scale={scale}", f"seed={seed}", f"config={config_hash}"]
    for table_name in sorted(table_hashes):
        parts.append(f"{table_name}={table_hashes[table_name]}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def build_manifest(
    *,
    generation_run_id: str,
    generator_version: str,
    seed: int,
    scenario: str,
    scale: str,
    period_start: str,
    period_end: str,
    config_hash: str,
    contract_version_set: str,
    table_row_counts: dict[str, int],
    table_hashes: dict[str, str],
    global_content_hash: str,
    started_at: str,
    finished_at: str,
    duration_seconds: float,
    status: str,
    validation_passed: bool,
    warnings: list[str],
    python_version: str,
) -> dict[str, object]:
    """The manifest.json content - no absolute paths, no personal
    information, per this phase's requirement."""
    return {
        "generation_run_id": generation_run_id,
        "generator_version": generator_version,
        "seed": seed,
        "scenario": scenario,
        "scale": scale,
        "period": {"start": period_start, "end": period_end},
        "config_hash": config_hash,
        "contract_version_set": contract_version_set,
        "tables": {
            name: {
                "row_count": table_row_counts.get(name, 0),
                "canonical_hash": table_hashes.get(name, ""),
            }
            for name in sorted(table_hashes)
        },
        "global_content_hash": global_content_hash,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "status": status,
        "validation_passed": validation_passed,
        "warnings": warnings,
        "environment": {"python_version": python_version},
    }


def write_manifest(manifest: dict[str, object], path: Path) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
