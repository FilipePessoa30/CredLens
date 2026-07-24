"""Load and validate data/metadata/source_registry.yaml.

The registry is the human/process-authored record of every candidate and
acquired data source: what it is, its license, and its lifecycle status.
Tooling (downloader, CLI) reads it; `validate_status_coherence` checks
that a source's declared status is actually backed by evidence (e.g. a
source cannot be `verified` without a manifest entry and an audit report).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from credlens.data.models import AcquisitionMethod, SourceRecord, SourceRole, SourceStatus

DEFAULT_REGISTRY_PATH = Path("data/metadata/source_registry.yaml")

_REQUIRED_FIELDS = [
    "id",
    "name",
    "role",
    "organization",
    "homepage",
    "acquisition_url",
    "acquisition_method",
    "filename",
    "authentication",
    "license",
    "license_url",
    "doi",
    "citation",
    "country",
    "period",
    "granularity",
    "observation_unit",
    "target_variable",
    "format",
    "update_frequency",
    "restrictions",
    "redistribution",
    "status",
    "verified_at_utc",
    "notes",
]


class RegistryError(Exception):
    """Raised for registry read, parse, or validation failures."""


def load_registry(path: Path | str | None = None) -> list[SourceRecord]:
    """Load and validate every source entry in the registry file.

    Raises:
        RegistryError: file missing/unreadable/invalid YAML, wrong shape,
            a source missing required fields, an invalid enum value, or a
            duplicate source id.
    """
    registry_path = Path(path) if path is not None else DEFAULT_REGISTRY_PATH

    if not registry_path.is_file():
        raise RegistryError(f"Source registry not found at '{registry_path}'.")

    try:
        raw_text = registry_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryError(f"Could not read source registry '{registry_path}': {exc}") from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise RegistryError(f"Source registry '{registry_path}' is not valid YAML: {exc}") from exc

    if not isinstance(data, dict) or "sources" not in data:
        raise RegistryError(
            f"Source registry '{registry_path}' must be a mapping with a top-level 'sources' list."
        )

    raw_sources = data["sources"]
    if not isinstance(raw_sources, list):
        raise RegistryError("'sources' must be a list.")

    records = [_parse_source(entry, index) for index, entry in enumerate(raw_sources)]
    _check_unique_ids(records)
    return records


def _parse_source(entry: Any, index: int) -> SourceRecord:
    if not isinstance(entry, dict):
        raise RegistryError(f"sources[{index}] must be a mapping.")

    missing = [field for field in _REQUIRED_FIELDS if field not in entry]
    if missing:
        raise RegistryError(
            f"sources[{index}] (id={entry.get('id', '?')}) missing required fields: {missing}"
        )

    try:
        role = SourceRole(entry["role"])
    except ValueError as exc:
        raise RegistryError(f"sources[{index}]: invalid role '{entry['role']}'.") from exc
    try:
        method = AcquisitionMethod(entry["acquisition_method"])
    except ValueError as exc:
        raise RegistryError(
            f"sources[{index}]: invalid acquisition_method '{entry['acquisition_method']}'."
        ) from exc
    try:
        status = SourceStatus(entry["status"])
    except ValueError as exc:
        raise RegistryError(f"sources[{index}]: invalid status '{entry['status']}'.") from exc

    return SourceRecord(
        id=str(entry["id"]),
        name=str(entry["name"]),
        role=role,
        organization=str(entry["organization"]),
        homepage=str(entry["homepage"]),
        acquisition_url=entry["acquisition_url"],
        acquisition_method=method,
        filename=entry["filename"],
        authentication=str(entry["authentication"]),
        license=str(entry["license"]),
        license_url=entry["license_url"],
        doi=entry["doi"],
        citation=str(entry["citation"]),
        country=str(entry["country"]),
        period=str(entry["period"]),
        granularity=str(entry["granularity"]),
        observation_unit=str(entry["observation_unit"]),
        target_variable=entry["target_variable"],
        format=str(entry["format"]),
        update_frequency=str(entry["update_frequency"]),
        restrictions=str(entry["restrictions"]),
        redistribution=str(entry["redistribution"]),
        status=status,
        verified_at_utc=entry["verified_at_utc"],
        notes=str(entry["notes"]),
    )


def _check_unique_ids(records: list[SourceRecord]) -> None:
    seen: set[str] = set()
    for record in records:
        if record.id in seen:
            raise RegistryError(f"Duplicate source id '{record.id}' in registry.")
        seen.add(record.id)


def get_source(records: list[SourceRecord], source_id: str) -> SourceRecord:
    """Look up a single source by id.

    Raises:
        RegistryError: no source with that id exists.
    """
    for record in records:
        if record.id == source_id:
            return record
    known = ", ".join(sorted(r.id for r in records))
    raise RegistryError(f"Unknown source id '{source_id}'. Known ids: {known}")


@dataclass(frozen=True)
class CoherenceIssue:
    source_id: str
    problem: str


def validate_status_coherence(
    records: list[SourceRecord],
    *,
    manifest_source_ids: set[str],
    audited_source_ids: set[str],
) -> list[CoherenceIssue]:
    """Check that each source's declared status is backed by real evidence.

    A status of `verified` requires both a manifest entry (file + checksum
    on disk) and an audit report; `downloaded` requires at least a
    manifest entry. Returns the list of issues found (empty if coherent) -
    it does not raise, so callers can decide how to surface incoherence.
    """
    issues: list[CoherenceIssue] = []
    for record in records:
        if record.status == SourceStatus.VERIFIED:
            if record.id not in manifest_source_ids:
                issues.append(
                    CoherenceIssue(record.id, "status is 'verified' but no manifest entry exists")
                )
            if record.id not in audited_source_ids:
                issues.append(
                    CoherenceIssue(record.id, "status is 'verified' but no audit report exists")
                )
        elif record.status == SourceStatus.DOWNLOADED and record.id not in manifest_source_ids:
            issues.append(
                CoherenceIssue(record.id, "status is 'downloaded' but no manifest entry exists")
            )
    return issues
