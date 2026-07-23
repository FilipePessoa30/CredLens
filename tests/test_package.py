"""Tests for the top-level credlens package."""

from __future__ import annotations

import re

import credlens


def test_package_is_importable() -> None:
    assert credlens is not None


def test_version_is_exposed() -> None:
    assert hasattr(credlens, "__version__")
    assert isinstance(credlens.__version__, str)
    assert credlens.__version__ != ""


def test_version_looks_like_semver() -> None:
    # Accepts the installed-package case (e.g. "0.1.0") and the
    # not-installed fallback (e.g. "0.0.0+unknown").
    assert re.match(r"^\d+\.\d+\.\d+(\+\w+)?$", credlens.__version__)
