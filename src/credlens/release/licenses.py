"""Dependency license inventory (Phase 10 release-engineering layer).

Reads license metadata from ALREADY-INSTALLED packages via
`importlib.metadata` - never a network call, never an external license
database. Labeled "Engineering license inventory - not legal advice"
throughout: this is a best-effort engineering aid for spotting obviously
incompatible or unknown licenses, not a legal compliance determination.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import distributions
from pathlib import Path
from typing import Any

DISCLAIMER_EN = "Engineering license inventory - not legal advice."
DISCLAIMER_PT_BR = "Inventário de licenças de engenharia - não é aconselhamento jurídico."

# Permissive licenses this project's own MIT license is unambiguously
# compatible with (informational classification only - see disclaimer).
_PERMISSIVE = {
    "MIT License",
    "MIT",
    "BSD License",
    "BSD",
    "Apache Software License",
    "Apache-2.0",
    "Apache 2.0",
    "Python Software Foundation License",
    "ISC License (ISCL)",
    "The Unlicense (Unlicense)",
    "Historical Permission Notice and Disclaimer (HPND)",
    "Mozilla Public License 2.0 (MPL 2.0)",
}
_COPYLEFT = {
    "GNU General Public License (GPL)",
    "GNU General Public License v2 (GPLv2)",
    "GNU General Public License v3 (GPLv3)",
    "GNU Lesser General Public License v2 (LGPLv2)",
    "GNU Lesser General Public License v3 (LGPLv3)",
    "GNU Affero General Public License v3 (AGPLv3)",
}


@dataclass(frozen=True)
class DependencyLicense:
    name: str
    version: str
    license: str
    compatibility: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "license": self.license,
            "compatibility": self.compatibility,
        }


@dataclass(frozen=True)
class LicenseInventory:
    project_license: str
    disclaimer_en: str
    disclaimer_pt_br: str
    dependencies: list[DependencyLicense]
    unknown_count: int
    copyleft_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_license": self.project_license,
            "disclaimer_en": self.disclaimer_en,
            "disclaimer_pt_br": self.disclaimer_pt_br,
            "n_dependencies": len(self.dependencies),
            "unknown_count": self.unknown_count,
            "copyleft_count": self.copyleft_count,
            "dependencies": [d.to_dict() for d in self.dependencies],
        }


def _short_license(metadata: Any) -> str:
    classifiers = [c for c in metadata.get_all("Classifier", []) if c.startswith("License")]
    if classifiers:
        # "License :: OSI Approved :: MIT License" -> "MIT License"
        return str(classifiers[0].split("::")[-1]).strip()
    raw = metadata.get("License")
    if raw and len(raw) < 80 and "\n" not in raw:
        return str(raw).strip()
    return "unknown"


def _compatibility(license_label: str) -> str:
    if license_label in _COPYLEFT:
        return "review_needed_copyleft"
    if license_label in _PERMISSIVE:
        return "permissive_compatible"
    if license_label == "unknown":
        return "unknown_review_needed"
    return "unclassified_review_needed"


def _project_license(repo_root: Path) -> str:
    path = repo_root / "LICENSE"
    if not path.is_file():
        return "unknown"
    text = path.read_text(encoding="utf-8", errors="ignore")
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    return first_line or "unknown"


def inventory_dependency_licenses(repo_root: Path | None = None) -> LicenseInventory:
    repo_root = repo_root or Path.cwd()
    rows = []
    seen: set[tuple[str, str]] = set()
    for dist in distributions():
        # Distribution.metadata is typed as the PackageMetadata Protocol,
        # which typeshed doesn't declare a `.get` method for even though
        # the real runtime object (email.message.Message) has one.
        metadata: Any = dist.metadata
        name = metadata.get("Name") or metadata.get("Summary") or "unknown"
        version = dist.version or "unknown"
        key = (name, version)
        if key in seen:
            continue
        seen.add(key)
        label = _short_license(dist.metadata)
        rows.append(
            DependencyLicense(
                name=name, version=version, license=label, compatibility=_compatibility(label)
            )
        )
    rows.sort(key=lambda r: r.name.lower())
    return LicenseInventory(
        project_license=_project_license(repo_root),
        disclaimer_en=DISCLAIMER_EN,
        disclaimer_pt_br=DISCLAIMER_PT_BR,
        dependencies=rows,
        unknown_count=sum(1 for r in rows if r.compatibility == "unknown_review_needed"),
        copyleft_count=sum(1 for r in rows if r.compatibility == "review_needed_copyleft"),
    )
