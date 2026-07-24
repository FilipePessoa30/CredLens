"""Typed models for data provenance: sources, files, and acquisition results.

These models describe *where data came from and how it was obtained* -
never the business/credit content of the data itself. See registry.py for
loading/validating data/metadata/source_registry.yaml into these types.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class SourceRole(StrEnum):
    """Why a source is in this project, per docs/dataset_selection.md."""

    PRIMARY_BENCHMARK = "primary_benchmark"
    SECONDARY_BENCHMARK = "secondary_benchmark"
    OPTIONAL_RESTRICTED = "optional_restricted"
    MARKET_CONTEXT = "market_context"
    FUTURE_SYNTHETIC = "future_synthetic"
    REJECTED = "rejected"


class SourceStatus(StrEnum):
    """Lifecycle state of a source. See registry.validate_status_coherence."""

    CANDIDATE = "candidate"
    APPROVED = "approved"
    DOWNLOADED = "downloaded"
    VERIFIED = "verified"
    BLOCKED = "blocked"
    REJECTED = "rejected"
    OPTIONAL = "optional"


class AcquisitionMethod(StrEnum):
    """How a source's raw data is (or would be) retrieved."""

    HTTP_GET = "http_get"
    BCB_SGS = "bcb_sgs"
    KAGGLE_API = "kaggle_api"


@dataclass(frozen=True)
class SourceRecord:
    """One entry of data/metadata/source_registry.yaml."""

    id: str
    name: str
    role: SourceRole
    organization: str
    homepage: str
    acquisition_url: str | None
    acquisition_method: AcquisitionMethod
    filename: str | None
    authentication: str
    license: str
    license_url: str | None
    doi: str | None
    citation: str
    country: str
    period: str
    granularity: str
    observation_unit: str
    target_variable: str | None
    format: str
    update_frequency: str
    restrictions: str
    redistribution: str
    status: SourceStatus
    verified_at_utc: str | None
    notes: str


@dataclass(frozen=True)
class ManifestEntry:
    """One row of data/metadata/file_manifest.csv."""

    source_id: str
    relative_path: str
    filename: str
    size_bytes: int
    sha256: str
    retrieved_at_utc: str
    url: str
    format: str
    num_rows: int | None
    num_columns: int | None
    verification_status: str
    source_version_or_date: str
    license: str
    notes: str


@dataclass(frozen=True)
class DownloadResult:
    """Outcome of a single successful acquisition (HTTP or BCB)."""

    source_id: str
    path: Path
    url: str
    final_url: str
    size_bytes: int
    sha256: str
    retrieved_at_utc: str
    content_type: str | None
