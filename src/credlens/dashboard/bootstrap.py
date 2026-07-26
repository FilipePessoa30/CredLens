"""Resolves a validated `DashboardConfig`/`DashboardData` pair for the
actual Streamlit scripts (Phase 7 section 19: explicit selection, no
silent overwrite; section 21: predictable startup).

Reads CLI args in `sys.argv` first (what `credlens dashboard run` passes
after `streamlit run dashboard/app.py --`), then falls back to
environment variables so each individual page script under
`dashboard/pages/` can also resolve the SAME config when Streamlit's
multipage router invokes it directly (and so `streamlit.testing.v1.
AppTest` can exercise one page file standalone). Auto-detection (no args,
no env vars) is a LAST resort, never a silent default when both a build
and a demo package are ambiguously available.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from credlens.dashboard.config import DashboardConfig, DashboardConfigError, resolve_config
from credlens.dashboard.data_access import (
    DashboardData,
    DataAccessError,
    list_available_builds,
    load_dashboard_data,
)
from credlens.dashboard.demo_package import load_demo_manifest
from credlens.dashboard.validation import DashboardValidationError, validate_dashboard_source

ENV_BUILD_ID = "CREDLENS_DASHBOARD_BUILD_ID"
ENV_DEMO = "CREDLENS_DASHBOARD_DEMO"
ENV_DEMO_DIR = "CREDLENS_DASHBOARD_DEMO_DIR"


class BootstrapError(Exception):
    """Raised when the dashboard cannot resolve an unambiguous, valid config."""


def _parse_argv(argv: list[str]) -> tuple[str | None, bool, str | None]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--build-id", default=None)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--demo-data-dir", default=None)
    known, _unknown = parser.parse_known_args(argv)
    return known.build_id, known.demo, known.demo_data_dir


def _config_from_environment() -> DashboardConfig | None:
    build_id = os.environ.get(ENV_BUILD_ID)
    demo = os.environ.get(ENV_DEMO) == "1"
    demo_dir = os.environ.get(ENV_DEMO_DIR)
    if build_id is None and not demo:
        return None
    return resolve_config(
        build_id=build_id,
        demo=demo,
        demo_data_dir=Path(demo_dir) if demo_dir else None,
    )


def _config_from_auto_detect() -> DashboardConfig:
    from credlens.dashboard.config import DEFAULT_DEMO_DATA_DIR

    demo_available = (DEFAULT_DEMO_DATA_DIR / "manifest.json").is_file()
    builds = list_available_builds()
    if demo_available and not builds:
        return resolve_config(demo=True)
    if builds and not demo_available:
        if len(builds) == 1:
            return resolve_config(build_id=builds[0])
        raise BootstrapError(
            f"Multiple builds are available ({builds}) and no demo package exists - pass "
            "--build-id explicitly (no implicit default, Phase 7 section 19)."
        )
    if demo_available and builds:
        raise BootstrapError(
            "Both a demo package and at least one warehouse build are available - pass "
            "--build-id or --demo explicitly (no implicit default, Phase 7 section 19)."
        )
    raise BootstrapError(
        "No warehouse build and no demo package found. Run `credlens dashboard export-demo "
        "--build-id <BUILD_ID>` first, or pass --build-id to a real build."
    )


def resolve_dashboard_config(argv: list[str] | None = None) -> DashboardConfig:
    argv = sys.argv[1:] if argv is None else argv
    build_id, demo, demo_dir = _parse_argv(argv)
    if build_id is not None or demo:
        return resolve_config(
            build_id=build_id, demo=demo, demo_data_dir=Path(demo_dir) if demo_dir else None
        )
    env_config = _config_from_environment()
    if env_config is not None:
        return env_config
    return _config_from_auto_detect()


def load_validated_dashboard_data(
    argv: list[str] | None = None,
) -> tuple[DashboardConfig, DashboardData]:
    """The one function every page script calls at the top. Raises
    `BootstrapError` for anything that should stop the page from
    rendering - callers must catch it and call `st.error` + `st.stop()`,
    never let a stack trace reach the user (Phase 7 section 16)."""
    try:
        config = resolve_dashboard_config(argv)
    except DashboardConfigError as exc:
        raise BootstrapError(str(exc)) from exc

    try:
        validate_dashboard_source(config)
    except DashboardValidationError as exc:
        raise BootstrapError(str(exc)) from exc

    try:
        data = load_dashboard_data(config)
    except DataAccessError as exc:
        raise BootstrapError(str(exc)) from exc

    return config, data


def demo_package_summary(demo_data_dir: Path) -> str:
    manifest = load_demo_manifest(demo_data_dir)
    return (
        f"Demo package v{manifest.demo_package_version} from build "
        f"'{manifest.source_build_id}' ({manifest.total_size_bytes:,} bytes)"
    )
