"""CredLens - Credit Risk & Portfolio Analytics.

Foundation-phase package. See docs/project_charter.md for scope.
"""

from __future__ import annotations

from importlib import metadata

try:
    __version__ = metadata.version("credlens")
except metadata.PackageNotFoundError:  # pragma: no cover - only if not installed
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
