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
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return _NULL_SENTINEL
    if isinstance(value, float):
        return repr(value)
    return str(value)


def canonical_table_hash(df: pd.DataFrame) -> str:
    if df.empty:
        columns_key = ",".join(sorted(df.columns.astype(str)))
        return hashlib.sha256(f"EMPTY:{columns_key}".encode()).hexdigest()

    ordered_columns = sorted(df.columns.astype(str))
    ordered = df[ordered_columns].astype(object)
    canonical_rows = ordered.map(_canonical_cell)
    row_strings = canonical_rows.apply(lambda row: "\x1f".join(row.to_numpy(dtype=str)), axis=1)
    sorted_rows = sorted(row_strings.tolist())
    blob = "\x1e".join(sorted_rows)
    header = ",".join(ordered_columns)
    return hashlib.sha256(f"{header}\x1d{blob}".encode()).hexdigest()


def canonical_config_hash(config: GenerationConfig) -> str:
    payload = config.model_dump(mode="json")
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
