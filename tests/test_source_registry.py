"""Tests for credlens.data.registry: schema validation and status coherence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from credlens.data.models import SourceRole, SourceStatus
from credlens.data.registry import (
    CoherenceIssue,
    RegistryError,
    get_source,
    load_registry,
    validate_status_coherence,
)


def _fixture_source(**overrides: Any) -> dict[str, Any]:
    source: dict[str, Any] = {
        "id": "fixture-a",
        "name": "Fixture Source",
        "role": "primary_benchmark",
        "organization": "Fixture Org",
        "homepage": "https://example.invalid/fixture",
        "acquisition_url": "https://example.invalid/fixture.csv",
        "acquisition_method": "http_get",
        "filename": "fixture.csv",
        "authentication": "none",
        "license": "CC BY 4.0",
        "license_url": "https://example.invalid/license",
        "doi": None,
        "citation": "Fixture citation.",
        "country": "Fixtureland",
        "period": "2020",
        "granularity": "row per fixture",
        "observation_unit": "fixture",
        "target_variable": "target",
        "format": "csv",
        "update_frequency": "static",
        "restrictions": "none",
        "redistribution": "allowed_with_attribution",
        "status": "candidate",
        "verified_at_utc": "2026-01-01T00:00:00Z",
        "notes": "Fixture note.",
    }
    source.update(overrides)
    return source


def _write_registry(tmp_path: Path, sources: list[dict[str, Any]]) -> Path:
    path = tmp_path / "source_registry.yaml"
    path.write_text(yaml.safe_dump({"schema_version": 1, "sources": sources}), encoding="utf-8")
    return path


def test_load_registry_reads_the_real_repository_registry() -> None:
    records = load_registry()

    assert len(records) == 5
    ids = {record.id for record in records}
    assert {"uci-default-credit", "south-german-credit", "home-credit"} <= ids
    for record in records:
        assert isinstance(record.role, SourceRole)
        assert isinstance(record.status, SourceStatus)


def test_load_registry_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="not found"):
        load_registry(tmp_path / "missing.yaml")


def test_load_registry_invalid_yaml_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("sources: [unclosed", encoding="utf-8")

    with pytest.raises(RegistryError, match="not valid YAML"):
        load_registry(path)


def test_load_registry_requires_sources_key(tmp_path: Path) -> None:
    path = tmp_path / "no_sources.yaml"
    path.write_text("schema_version: 1\n", encoding="utf-8")

    with pytest.raises(RegistryError, match="top-level 'sources' list"):
        load_registry(path)


def test_load_registry_missing_required_field_raises(tmp_path: Path) -> None:
    source = _fixture_source()
    del source["license"]
    path = _write_registry(tmp_path, [source])

    with pytest.raises(RegistryError, match="missing required fields"):
        load_registry(path)


def test_load_registry_invalid_role_raises(tmp_path: Path) -> None:
    path = _write_registry(tmp_path, [_fixture_source(role="not_a_real_role")])

    with pytest.raises(RegistryError, match="invalid role"):
        load_registry(path)


def test_load_registry_invalid_acquisition_method_raises(tmp_path: Path) -> None:
    path = _write_registry(tmp_path, [_fixture_source(acquisition_method="carrier_pigeon")])

    with pytest.raises(RegistryError, match="invalid acquisition_method"):
        load_registry(path)


def test_load_registry_invalid_status_raises(tmp_path: Path) -> None:
    path = _write_registry(tmp_path, [_fixture_source(status="not_a_real_status")])

    with pytest.raises(RegistryError, match="invalid status"):
        load_registry(path)


def test_load_registry_duplicate_ids_raises(tmp_path: Path) -> None:
    path = _write_registry(tmp_path, [_fixture_source(id="dup"), _fixture_source(id="dup")])

    with pytest.raises(RegistryError, match="Duplicate source id"):
        load_registry(path)


def test_get_source_returns_matching_record(tmp_path: Path) -> None:
    records = load_registry(_write_registry(tmp_path, [_fixture_source(id="fixture-a")]))

    record = get_source(records, "fixture-a")
    assert record.id == "fixture-a"
    assert record.role == SourceRole.PRIMARY_BENCHMARK


def test_get_source_unknown_id_raises(tmp_path: Path) -> None:
    records = load_registry(_write_registry(tmp_path, [_fixture_source(id="fixture-a")]))

    with pytest.raises(RegistryError, match="Unknown source id"):
        get_source(records, "does-not-exist")


def test_validate_status_coherence_flags_verified_without_manifest(tmp_path: Path) -> None:
    records = load_registry(
        _write_registry(tmp_path, [_fixture_source(id="fixture-a", status="verified")])
    )

    issues = validate_status_coherence(records, manifest_source_ids=set(), audited_source_ids=set())

    assert issues == [
        CoherenceIssue("fixture-a", "status is 'verified' but no manifest entry exists"),
        CoherenceIssue("fixture-a", "status is 'verified' but no audit report exists"),
    ]


def test_validate_status_coherence_flags_downloaded_without_manifest(tmp_path: Path) -> None:
    records = load_registry(
        _write_registry(tmp_path, [_fixture_source(id="fixture-a", status="downloaded")])
    )

    issues = validate_status_coherence(records, manifest_source_ids=set(), audited_source_ids=set())

    assert issues == [
        CoherenceIssue("fixture-a", "status is 'downloaded' but no manifest entry exists")
    ]


def test_validate_status_coherence_passes_when_evidence_present(tmp_path: Path) -> None:
    records = load_registry(
        _write_registry(tmp_path, [_fixture_source(id="fixture-a", status="verified")])
    )

    issues = validate_status_coherence(
        records, manifest_source_ids={"fixture-a"}, audited_source_ids={"fixture-a"}
    )

    assert issues == []


def test_validate_status_coherence_ignores_candidate_and_blocked(tmp_path: Path) -> None:
    records = load_registry(
        _write_registry(
            tmp_path,
            [
                _fixture_source(id="fixture-candidate", status="candidate"),
                _fixture_source(id="fixture-blocked", status="blocked"),
            ],
        )
    )

    issues = validate_status_coherence(records, manifest_source_ids=set(), audited_source_ids=set())

    assert issues == []
