"""CycloneDX-format Software Bill of Materials (Phase 10 release-
engineering layer).

Built from already-installed packages' own metadata
(`importlib.metadata`) - no network call, no third-party SBOM service.
Uses the standard library only (no new dependency added for this - a
lightweight `cyclonedx-bom` generator would need its own PyPI package;
hand-building the well-documented, simple CycloneDX JSON schema's
component list directly is both lighter-weight and keeps this fully
offline/local).

Producing an SBOM here is NOT a claim of supply-chain-security
compliance (no vulnerability scanning, no provenance attestation) - it
is an inventory artifact only, exactly what CycloneDX's `component` list
is designed to hold.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from importlib.metadata import distributions
from pathlib import Path
from typing import Any

CYCLONEDX_SPEC_VERSION = "1.5"
NOT_A_SUPPLY_CHAIN_COMPLIANCE_CLAIM_EN = (
    "This SBOM is an inventory artifact only - it does not constitute a supply-chain security "
    "or vulnerability-scanning compliance claim."
)


@dataclass(frozen=True)
class SbomReport:
    bom_format: str
    spec_version: str
    serial_number: str
    n_components: int
    content_fingerprint: str
    components: list[dict[str, Any]]
    disclaimer_en: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "bomFormat": self.bom_format,
            "specVersion": self.spec_version,
            "serialNumber": self.serial_number,
            "version": 1,
            "n_components": self.n_components,
            "content_fingerprint": self.content_fingerprint,
            "disclaimer_en": self.disclaimer_en,
            "components": self.components,
        }


def _purl(name: str, version: str) -> str:
    normalized = name.lower().replace("_", "-").replace(".", "-")
    return f"pkg:pypi/{normalized}@{version}"


def generate_sbom(repo_root: Path | None = None, *, seed_serial: str | None = None) -> SbomReport:
    """`content_fingerprint` hashes only the component list (name,
    version, purl) - deterministic across runs on the SAME environment,
    independent of `serialNumber` (a fresh UUID per generation, per the
    CycloneDX spec) or any timestamp, mirroring this project's established
    "deterministic content vs. execution timestamp" separation."""
    repo_root = repo_root or Path.cwd()
    _ = repo_root
    components = []
    seen: set[tuple[str, str]] = set()
    for dist in distributions():
        # See credlens.release.licenses for why this is typed Any - a
        # typeshed gap on PackageMetadata, not a real runtime issue.
        metadata: Any = dist.metadata
        name = metadata.get("Name") or "unknown"
        version = dist.version or "0.0.0"
        key = (name, version)
        if key in seen:
            continue
        seen.add(key)
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": _purl(name, version),
            }
        )
    components.sort(key=lambda c: (c["name"].lower(), c["version"]))

    fingerprint_source = json.dumps(
        [{"name": c["name"], "version": c["version"], "purl": c["purl"]} for c in components],
        sort_keys=True,
    ).encode("utf-8")
    content_fingerprint = hashlib.sha256(fingerprint_source).hexdigest()

    serial = seed_serial or str(uuid.uuid4())
    return SbomReport(
        bom_format="CycloneDX",
        spec_version=CYCLONEDX_SPEC_VERSION,
        serial_number=f"urn:uuid:{serial}",
        n_components=len(components),
        content_fingerprint=content_fingerprint,
        components=components,
        disclaimer_en=NOT_A_SUPPLY_CHAIN_COMPLIANCE_CLAIM_EN,
    )


def write_sbom(report: SbomReport, *, repo_root: Path | None = None) -> Path:
    repo_root = repo_root or Path.cwd()
    out_dir = repo_root / "reports" / "release"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "sbom.cyclonedx.json"
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return path
