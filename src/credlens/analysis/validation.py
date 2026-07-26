"""Gates a build must pass before the analysis layer will touch it
(Phase 6 section 18): existence, a clean test result, unmutated raw
sources (gate C), and a supported build. Every entry point in
`credlens.analysis` calls `validate_build_for_analysis` first - the
analysis layer never queries a build it has not itself re-checked, even
though `credlens warehouse build` already checked most of this once.
"""

from __future__ import annotations

from credlens.warehouse.build import BuildError, BuildManifest, load_build_manifest
from credlens.warehouse.integrity import RawIntegrityError, verify_build_sources


class AnalysisValidationError(Exception):
    """Raised when a build is not safe/complete enough to analyze."""


def validate_build_for_analysis(build_id: str) -> BuildManifest:
    """Loads a build manifest and re-validates it is safe to analyze.
    Refuses: a nonexistent build id; a build whose own dbt tests did not
    all pass; a build whose final_status was not 'success'; a build whose
    raw sources have been mutated/deleted/quarantined since the build ran
    (gate C). Returns the manifest on success - never a partial result."""
    try:
        manifest = load_build_manifest(build_id)
    except BuildError as exc:
        raise AnalysisValidationError(f"No usable build '{build_id}': {exc}") from exc

    if manifest.final_status != "success":
        raise AnalysisValidationError(
            f"Build '{build_id}' has final_status={manifest.final_status!r}, not 'success' - "
            "refusing to analyze a failed build."
        )
    failed = manifest.test_results.get("failed", 0)
    errored = manifest.test_results.get("errored", 0)
    if failed or errored:
        raise AnalysisValidationError(
            f"Build '{build_id}' has {failed} failed and {errored} errored dbt test(s) - "
            "refusing to analyze a build with known-bad data quality."
        )
    if not manifest.analytical_fingerprint:
        raise AnalysisValidationError(
            f"Build '{build_id}' has no analytical_fingerprint recorded - refusing to treat "
            "it as a complete, trustworthy build."
        )

    try:
        verify_build_sources(manifest.sources)
    except RawIntegrityError as exc:
        raise AnalysisValidationError(
            f"Build '{build_id}' failed raw source integrity verification - its source data "
            f"has changed since the build ran:\n{exc}"
        ) from exc

    return manifest
