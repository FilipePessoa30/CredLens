"""Dashboard mode/config resolution (Phase 7 section 10, 16, 18.3).

Two modes only:

  - `warehouse`: reads a real, already-built, already-tested DuckDB
    warehouse via `credlens.analysis.validation.validate_build_for_analysis`
    (the SAME gate `credlens analysis run` uses - never a separate,
    weaker check).
  - `demo`: reads a small, versioned Parquet package
    (`dashboard/demo_data/`) with no `data/warehouse/` dependency at all.

Nothing here accepts an arbitrary filesystem path from user input without
validation: a warehouse `build_id` must resolve to a real build under
`data/warehouse/<build_id>/` via the existing build-manifest loader (which
itself refuses a build whose id contains path-traversal characters - see
`credlens.warehouse.build.load_build_manifest`), and the demo package path
defaults to the single, versioned `dashboard/demo_data/` location.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DashboardMode = Literal["warehouse", "demo"]

DEFAULT_DEMO_DATA_DIR = Path("dashboard/demo_data")
DEFAULT_PORT = 8501


class DashboardConfigError(Exception):
    """Raised when the dashboard cannot resolve a safe mode/build to run against."""


@dataclass(frozen=True)
class DashboardConfig:
    mode: DashboardMode
    build_id: str | None
    demo_data_dir: Path
    port: int
    open_browser: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "build_id": self.build_id,
            "demo_data_dir": str(self.demo_data_dir),
            "port": self.port,
            "open_browser": self.open_browser,
        }


def resolve_config(
    *,
    build_id: str | None = None,
    demo: bool = False,
    demo_data_dir: Path | None = None,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
) -> DashboardConfig:
    """Resolves an unambiguous, validated dashboard configuration.
    Refuses `--build-id` and `--demo` given together (explicit selection,
    Phase 7 section 19: "nenhuma sobrescrita silenciosa"); refuses
    neither given (no implicit default mode)."""
    if build_id is not None and demo:
        raise DashboardConfigError(
            "Both --build-id and --demo were given - pick exactly one mode explicitly."
        )
    if build_id is None and not demo:
        raise DashboardConfigError(
            "Neither --build-id nor --demo was given - pass --build-id <BUILD_ID> for the "
            "validated-warehouse mode, or --demo for the demo aggregate mode."
        )
    if not (1 <= port <= 65535):
        raise DashboardConfigError(f"--port {port} is not a valid TCP port (1-65535).")

    if demo:
        return DashboardConfig(
            mode="demo",
            build_id=None,
            demo_data_dir=demo_data_dir or DEFAULT_DEMO_DATA_DIR,
            port=port,
            open_browser=open_browser,
        )

    assert build_id is not None  # narrowed above
    if not build_id or any(ch in build_id for ch in ("..", "/", "\\", "\x00")):
        raise DashboardConfigError(f"--build-id {build_id!r} is not a well-formed build id.")

    return DashboardConfig(
        mode="warehouse",
        build_id=build_id,
        demo_data_dir=demo_data_dir or DEFAULT_DEMO_DATA_DIR,
        port=port,
        open_browser=open_browser,
    )
