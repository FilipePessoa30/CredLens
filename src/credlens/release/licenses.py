"""Dependency license inventory (Phase 10 release-engineering layer).

Reads license metadata from ALREADY-INSTALLED packages via
`importlib.metadata` - never a network call, never an external license
database. Labeled "Engineering license inventory - not legal advice"
throughout: this is a best-effort engineering aid for spotting obviously
incompatible or unknown licenses, not a legal compliance determination.
"""

from __future__ import annotations

import re
import tomllib
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

# PEP 639 `License-Expression` (SPDX identifiers) - increasingly common in
# newer package metadata INSTEAD OF trove `Classifier: License :: ...`
# entries (numpy 2.x, pydantic 2.x, scikit-learn, mypy, ruff all ship
# `License-Expression` only, no License classifier at all - a real,
# empirically-found gap this project's original classifier-only check
# missed, showing these well-known-permissive packages as "unknown").
_SPDX_PERMISSIVE = {
    "MIT",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "0BSD",
    "Apache-2.0",
    "ISC",
    "Zlib",
    "CC0-1.0",
    "Unlicense",
    "HPND",
    "MPL-2.0",
    "PSF-2.0",
    "Python-2.0",
}
_SPDX_COPYLEFT = {
    "GPL-2.0",
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0",
    "GPL-3.0-only",
    "GPL-3.0-or-later",
    "LGPL-2.1",
    "LGPL-2.1-only",
    "LGPL-2.1-or-later",
    "LGPL-3.0",
    "LGPL-3.0-only",
    "LGPL-3.0-or-later",
    "AGPL-3.0",
    "AGPL-3.0-only",
    "AGPL-3.0-or-later",
}


def _normalize_name(name: str) -> str:
    """PEP 503 normalization - the only reliable way to match a
    `pyproject.toml` requirement string against an installed
    distribution's metadata `Name` (case and `-`/`_`/`.` differ freely
    between the two in practice)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(requirement: str) -> str:
    # Strips version specifiers/markers/extras - "dbt-core>=1.12.0" ->
    # "dbt-core", "pytest-cov>=5.0,<6" -> "pytest-cov".
    match = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return _normalize_name(match.group(1)) if match else _normalize_name(requirement)


def load_direct_dependency_roles(repo_root: Path) -> dict[str, list[str]]:
    """Maps normalized package name -> every declared role it has
    (`runtime`, an extra name like `warehouse`/`analysis`/`dashboard`/
    `modeling`/`notebook`, or `dev`) DIRECTLY from `pyproject.toml` -
    never inferred from what happens to be installed, so a package only
    pulled in transitively is never mistaken for a direct one. Returns an
    empty mapping (every dependency treated as transitive) if `repo_root`
    has no `pyproject.toml` at all - a legitimate case for an isolated
    test fixture, not an error condition this function should raise on."""
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.is_file():
        return {}
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    roles: dict[str, list[str]] = {}

    def _add(requirements: list[str], role: str) -> None:
        for req in requirements:
            name = _requirement_name(req)
            roles.setdefault(name, [])
            if role not in roles[name]:
                roles[name].append(role)

    _add(pyproject.get("project", {}).get("dependencies", []), "runtime")
    optional = pyproject.get("project", {}).get("optional-dependencies", {})
    for extra, requirements in optional.items():
        _add(requirements, extra)
    for group, requirements in pyproject.get("dependency-groups", {}).items():
        _add(requirements, group)
    return roles


@dataclass(frozen=True)
class DependencyLicense:
    name: str
    version: str
    license: str
    compatibility: str
    dependency_kind: str  # "direct" | "transitive"
    roles: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "license": self.license,
            "compatibility": self.compatibility,
            "dependency_kind": self.dependency_kind,
            "roles": self.roles,
        }


@dataclass(frozen=True)
class LicenseInventory:
    project_license: str
    disclaimer_en: str
    disclaimer_pt_br: str
    dependencies: list[DependencyLicense]
    unknown_count: int
    copyleft_count: int

    @property
    def direct_count(self) -> int:
        return sum(1 for d in self.dependencies if d.dependency_kind == "direct")

    @property
    def transitive_count(self) -> int:
        return sum(1 for d in self.dependencies if d.dependency_kind == "transitive")

    @property
    def direct_unknown_license_count(self) -> int:
        return sum(
            1 for d in self.dependencies if d.compatibility == "direct_unknown_license_needs_review"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_license": self.project_license,
            "disclaimer_en": self.disclaimer_en,
            "disclaimer_pt_br": self.disclaimer_pt_br,
            "n_dependencies": len(self.dependencies),
            "unknown_count": self.unknown_count,
            "copyleft_count": self.copyleft_count,
            "direct_count": self.direct_count,
            "transitive_count": self.transitive_count,
            "direct_unknown_license_count": self.direct_unknown_license_count,
            "dependencies": [d.to_dict() for d in self.dependencies],
        }


# The MIT License's own canonical, distinguishing opening clause
# (opensource.org/licenses/MIT), whitespace-normalized/lower-cased for
# matching - used ONLY to recognize that exact well-known text, never as
# a package-name allowlist (Phase 10C: found via `importlib.metadata`
# that kaleido/choreographer/logistro all embed their FULL license text,
# not a short label, in the legacy `License` field - verified against
# each package's own installed `licenses/LICENSE.md`/`LICENSE` file).
_MIT_LICENSE_SIGNATURE = "permission is hereby granted, free of charge, to any person"


def _is_full_text_mit_license(raw_license_field: str) -> bool:
    """True if `raw_license_field` (typically long, multi-line - the
    exact case the short-single-line heuristic below cannot classify)
    contains the MIT License's own canonical opening clause verbatim,
    modulo whitespace/case. Detects the license by its own defining text,
    never by which package happens to ship it."""
    normalized = " ".join(raw_license_field.lower().split())
    return _MIT_LICENSE_SIGNATURE in normalized


def _short_license(metadata: Any) -> str:
    # PEP 639 `License-Expression` (SPDX) checked FIRST - it is the more
    # modern, structured field and, empirically, several well-known
    # permissively-licensed packages (numpy 2.x, pydantic 2.x, scikit-
    # learn, mypy, ruff) ship ONLY this field, no `License` classifier at
    # all.
    expression = metadata.get("License-Expression")
    if expression:
        return str(expression).strip()
    classifiers = [c for c in metadata.get_all("Classifier", []) if c.startswith("License")]
    if classifiers:
        # "License :: OSI Approved :: MIT License" -> "MIT License"
        return str(classifiers[0].split("::")[-1]).strip()
    raw = metadata.get("License")
    if raw and len(raw) < 80 and "\n" not in raw:
        return str(raw).strip()
    if raw and _is_full_text_mit_license(raw):
        return "MIT License"
    return "unknown"


def _spdx_compatibility(license_label: str) -> str | None:
    """A `License-Expression` can combine several SPDX identifiers with
    `AND`/`OR` (e.g. numpy's "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND
    CC0-1.0" - vendored third-party notices, not numpy's own license).
    Returns `None` if the label doesn't look like an SPDX expression at
    all (falls through to the free-text classification below)."""
    tokens = re.split(r"\s+(?:AND|OR)\s+", license_label)
    if not all(re.fullmatch(r"[A-Za-z0-9.\-]+", t) for t in tokens):
        return None
    if any(t in _SPDX_COPYLEFT for t in tokens):
        return "review_needed_copyleft"
    if all(t in _SPDX_PERMISSIVE for t in tokens):
        return "permissive_compatible"
    return None


def _compatibility(license_label: str, *, is_direct: bool) -> str:
    spdx_result = _spdx_compatibility(license_label)
    if spdx_result is not None:
        return spdx_result
    if license_label in _COPYLEFT:
        return "review_needed_copyleft"
    if license_label in _PERMISSIVE:
        return "permissive_compatible"
    if license_label == "unknown":
        # Phase 10B: a DIRECT dependency with no identifiable license is a
        # sharper finding than a transitive one - this project chose to
        # depend on it directly, so "unknown, review later" is not an
        # acceptable resting state the way it can be for something pulled
        # in two levels down by a direct dependency's own dependency.
        return "direct_unknown_license_needs_review" if is_direct else "unknown_review_needed"
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
    direct_roles = load_direct_dependency_roles(repo_root)
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
        roles = direct_roles.get(_normalize_name(name), [])
        is_direct = bool(roles)
        rows.append(
            DependencyLicense(
                name=name,
                version=version,
                license=label,
                compatibility=_compatibility(label, is_direct=is_direct),
                dependency_kind="direct" if is_direct else "transitive",
                roles=roles,
            )
        )
    rows.sort(key=lambda r: r.name.lower())
    return LicenseInventory(
        project_license=_project_license(repo_root),
        disclaimer_en=DISCLAIMER_EN,
        disclaimer_pt_br=DISCLAIMER_PT_BR,
        dependencies=rows,
        unknown_count=sum(
            1
            for r in rows
            if r.compatibility in ("unknown_review_needed", "direct_unknown_license_needs_review")
        ),
        copyleft_count=sum(1 for r in rows if r.compatibility == "review_needed_copyleft"),
    )
