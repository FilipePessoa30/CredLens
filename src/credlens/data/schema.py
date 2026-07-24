"""Lightweight declarative schema for a raw tabular source.

This is deliberately not a full validation framework (Pandera and similar
are scoped to a later phase - see docs/architecture.md). It only records
which columns a source's own documentation says should exist, so a
profiling run can flag a divergence between "the file we got" and "what
the source documents" instead of silently ignoring it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class SchemaError(Exception):
    """Raised for schema file read/parse failures."""


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    description: str
    expected_type: str  # informational: "integer" | "categorical" | "binary" | "string"


@dataclass(frozen=True)
class DatasetSchema:
    source_id: str
    columns: list[ColumnSpec]

    @property
    def column_names(self) -> list[str]:
        return [column.name for column in self.columns]


def load_schema(path: Path) -> DatasetSchema:
    """Load a documented schema from `data/metadata/schemas/<source_id>.yaml`.

    Raises:
        SchemaError: file missing, invalid YAML, or missing required keys.
    """
    if not path.is_file():
        raise SchemaError(f"Schema file not found at '{path}'.")

    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SchemaError(f"Schema file '{path}' is not valid YAML: {exc}") from exc

    if not isinstance(data, dict) or "source_id" not in data or "columns" not in data:
        raise SchemaError(f"Schema file '{path}' must have 'source_id' and 'columns' keys.")

    raw_columns = data["columns"]
    if not isinstance(raw_columns, list):
        raise SchemaError(f"Schema file '{path}': 'columns' must be a list.")

    columns: list[ColumnSpec] = []
    for index, col in enumerate(raw_columns):
        if not isinstance(col, dict) or "name" not in col:
            raise SchemaError(f"Schema file '{path}': columns[{index}] must have a 'name'.")
        columns.append(
            ColumnSpec(
                name=str(col["name"]),
                description=str(col.get("description", "")),
                expected_type=str(col.get("expected_type", "unknown")),
            )
        )

    return DatasetSchema(source_id=str(data["source_id"]), columns=columns)


@dataclass(frozen=True)
class SchemaComparison:
    unexpected_columns: list[str]
    missing_columns: list[str]

    @property
    def is_coherent(self) -> bool:
        return not self.unexpected_columns and not self.missing_columns


def compare_columns(schema: DatasetSchema, actual_columns: list[str]) -> SchemaComparison:
    """Compare a schema's documented columns against a file's actual columns."""
    expected = set(schema.column_names)
    actual = set(actual_columns)
    return SchemaComparison(
        unexpected_columns=sorted(actual - expected),
        missing_columns=sorted(expected - actual),
    )
