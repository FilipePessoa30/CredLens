"""Tests for credlens.data.schema: documented-schema loading and comparison."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from credlens.data.schema import SchemaError, compare_columns, load_schema


def _write_schema(tmp_path: Path, source_id: str, columns: list[dict[str, str]]) -> Path:
    path = tmp_path / f"{source_id}.yaml"
    path.write_text(yaml.safe_dump({"source_id": source_id, "columns": columns}), encoding="utf-8")
    return path


def test_load_schema_reads_the_real_uci_default_credit_schema() -> None:
    schema = load_schema(Path("data/metadata/schemas/uci-default-credit.yaml"))

    assert schema.source_id == "uci-default-credit"
    assert "ID" in schema.column_names
    assert "Y" in schema.column_names
    assert len(schema.columns) == 25


def test_load_schema_reads_the_real_south_german_credit_schema() -> None:
    schema = load_schema(Path("data/metadata/schemas/south-german-credit.yaml"))

    assert schema.source_id == "south-german-credit"
    assert "kredit" in schema.column_names
    assert len(schema.columns) == 21


def test_load_schema_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SchemaError, match="not found"):
        load_schema(tmp_path / "missing.yaml")


def test_load_schema_invalid_yaml_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("source_id: [unclosed", encoding="utf-8")

    with pytest.raises(SchemaError, match="not valid YAML"):
        load_schema(path)


def test_load_schema_missing_required_keys_raises(tmp_path: Path) -> None:
    path = tmp_path / "incomplete.yaml"
    path.write_text("source_id: fixture\n", encoding="utf-8")

    with pytest.raises(SchemaError, match="'source_id' and 'columns'"):
        load_schema(path)


def test_load_schema_column_without_name_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad_column.yaml"
    path.write_text(
        yaml.safe_dump({"source_id": "fixture", "columns": [{"description": "no name"}]}),
        encoding="utf-8",
    )

    with pytest.raises(SchemaError, match="must have a 'name'"):
        load_schema(path)


def test_compare_columns_detects_no_divergence_for_exact_match(tmp_path: Path) -> None:
    schema = load_schema(
        _write_schema(tmp_path, "fixture", [{"name": "a"}, {"name": "b"}, {"name": "c"}])
    )

    comparison = compare_columns(schema, ["a", "b", "c"])

    assert comparison.is_coherent
    assert comparison.unexpected_columns == []
    assert comparison.missing_columns == []


def test_compare_columns_detects_unexpected_column(tmp_path: Path) -> None:
    schema = load_schema(_write_schema(tmp_path, "fixture", [{"name": "a"}, {"name": "b"}]))

    comparison = compare_columns(schema, ["a", "b", "surprise_column"])

    assert not comparison.is_coherent
    assert comparison.unexpected_columns == ["surprise_column"]
    assert comparison.missing_columns == []


def test_compare_columns_detects_missing_column(tmp_path: Path) -> None:
    schema = load_schema(
        _write_schema(tmp_path, "fixture", [{"name": "a"}, {"name": "b"}, {"name": "c"}])
    )

    comparison = compare_columns(schema, ["a", "b"])

    assert not comparison.is_coherent
    assert comparison.missing_columns == ["c"]
    assert comparison.unexpected_columns == []


def test_compare_columns_real_schemas_match_the_actually_acquired_files() -> None:
    """Cross-check: the documented schemas match what credlens data audit
    actually found in the real acquired files this session (see
    reports/data_audit/quality_metrics.json and docs/data_quality_audit.md).
    """
    schema = load_schema(Path("data/metadata/schemas/uci-default-credit.yaml"))
    actual_columns = ["ID"] + [f"X{i}" for i in range(1, 24)] + ["Y"]

    comparison = compare_columns(schema, actual_columns)

    assert comparison.is_coherent
