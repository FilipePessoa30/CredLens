"""Pre-flight validation for the dashboard (Phase 7 sections 10, 16, 19,
20). `credlens dashboard validate` and the app's own startup path both
call `validate_dashboard_source` - the dashboard must never render data
from a build/package it has not itself re-checked, even though the
underlying build/demo tooling already checked most of this once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from credlens.analysis.validation import AnalysisValidationError, validate_build_for_analysis
from credlens.dashboard.config import DashboardConfig
from credlens.dashboard.demo_package import DemoPackageError, validate_demo_package


class DashboardValidationError(Exception):
    """Raised when a build/demo package is not safe to display."""


@dataclass(frozen=True)
class ValidationReport:
    mode: str
    ok: bool
    build_id: str | None
    fingerprint: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "ok": self.ok,
            "build_id": self.build_id,
            "fingerprint": self.fingerprint,
            "detail": self.detail,
        }


def validate_dashboard_source(config: DashboardConfig) -> ValidationReport:
    if config.mode == "warehouse":
        assert config.build_id is not None
        try:
            build = validate_build_for_analysis(config.build_id)
        except AnalysisValidationError as exc:
            raise DashboardValidationError(str(exc)) from exc
        if build.suite_id is None:
            raise DashboardValidationError(
                f"Build '{config.build_id}' has no suite_id - the dashboard needs a suite "
                "(baseline + scenarios), not a single run."
            )
        return ValidationReport(
            mode="warehouse",
            ok=True,
            build_id=build.build_id,
            fingerprint=build.analytical_fingerprint,
            detail=(
                f"Build '{build.build_id}' passed re-validation: dbt tests "
                f"{build.test_results.get('passed')} passed / "
                f"{build.test_results.get('failed')} failed, raw sources unmutated."
            ),
        )

    try:
        manifest = validate_demo_package(config.demo_data_dir)
    except DemoPackageError as exc:
        raise DashboardValidationError(str(exc)) from exc
    return ValidationReport(
        mode="demo",
        ok=True,
        build_id=manifest.source_build_id,
        fingerprint=manifest.warehouse_fingerprint,
        detail=(
            f"Demo package at '{config.demo_data_dir}' passed integrity verification: "
            f"{len(manifest.tables)} table(s), {manifest.total_size_bytes:,} bytes."
        ),
    )
