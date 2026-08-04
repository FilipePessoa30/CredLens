"""Tests for credlens.analysis.validation (Phase 6 section 18): the
analysis layer must re-validate a build itself - tests passed, sources
unmutated - never trust a build's own manifest blindly. Builds a real
isolated-root suite warehouse once per module (Phase 6 gate B) and reuses
it read-only across every test."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.analysis.validation import AnalysisValidationError, validate_build_for_analysis
from credlens.generation.suite import generate_suite
from credlens.generation.testing_support import (
    isolated_manifest_dir,
    isolated_output_dirs,
    safe_rmtree,
)
from credlens.warehouse.build import (
    _rmtree_with_retry,
    build_dir_for,
    load_build_manifest,
    run_build,
)

# Fase 11B - see tests/test_warehouse_build.py's own comment: this file
# was never marked slow, causing the dedicated CI job's slow-test step
# to exit 5 ("no tests collected").
pytestmark = pytest.mark.slow

_SEED = 703_501
_BUILD_ID = "BUILD_pytest_analysis_validation"


@pytest.fixture(scope="module")
def isolated_suite(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path, Path]]:
    tmp_path = tmp_path_factory.mktemp("analysis_validation")
    operational_dir, truth_dir = isolated_output_dirs(tmp_path)
    manifest_dir = isolated_manifest_dir(tmp_path)
    outcome = generate_suite(
        scale_name="smoke",
        seed=_SEED,
        force=True,
        output_dirs=(operational_dir, truth_dir),
        manifest_dir=manifest_dir,
    )
    yield outcome.suite_id, operational_dir, manifest_dir
    safe_rmtree(tmp_path, allowed_root=tmp_path)


@pytest.fixture(scope="module")
def a_built_suite(isolated_suite: tuple[str, Path, Path]) -> Iterator[str]:
    suite_id, operational_dir, manifest_dir = isolated_suite
    manifest = run_build(
        suite_id=suite_id,
        build_id=_BUILD_ID,
        force=True,
        operational_root=operational_dir,
        manifest_dir=manifest_dir,
    )
    assert manifest.final_status == "success"
    yield manifest.build_id
    build_dir = build_dir_for(_BUILD_ID)
    if build_dir.exists():
        try:
            _rmtree_with_retry(build_dir)
        except PermissionError:
            shutil.rmtree(build_dir, ignore_errors=True)


class TestValidateBuildForAnalysis:
    def test_a_clean_successful_build_validates(self, a_built_suite: str) -> None:
        manifest = validate_build_for_analysis(a_built_suite)
        assert manifest.build_id == a_built_suite
        assert manifest.final_status == "success"
        assert manifest.suite_id is not None

    def test_nonexistent_build_id_raises(self) -> None:
        with pytest.raises(AnalysisValidationError, match="No usable build"):
            validate_build_for_analysis("BUILD_does_not_exist_at_all_0000")

    def test_build_with_failed_dbt_tests_is_refused(
        self, a_built_suite: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_manifest = load_build_manifest(a_built_suite)
        broken = real_manifest.__class__(
            **{**real_manifest.to_dict(), "test_results": {"passed": 1, "failed": 2, "errored": 0}}
        )

        def _fake_load(build_id: str) -> object:
            assert build_id == a_built_suite
            return broken

        monkeypatch.setattr("credlens.analysis.validation.load_build_manifest", _fake_load)
        with pytest.raises(AnalysisValidationError, match="failed"):
            validate_build_for_analysis(a_built_suite)

    def test_build_with_non_success_final_status_is_refused(
        self, a_built_suite: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_manifest = load_build_manifest(a_built_suite)
        broken = real_manifest.__class__(**{**real_manifest.to_dict(), "final_status": "failed"})
        monkeypatch.setattr("credlens.analysis.validation.load_build_manifest", lambda _bid: broken)
        with pytest.raises(AnalysisValidationError, match="final_status"):
            validate_build_for_analysis(a_built_suite)

    def test_build_with_no_fingerprint_is_refused(
        self, a_built_suite: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_manifest = load_build_manifest(a_built_suite)
        broken = real_manifest.__class__(
            **{**real_manifest.to_dict(), "analytical_fingerprint": ""}
        )
        monkeypatch.setattr("credlens.analysis.validation.load_build_manifest", lambda _bid: broken)
        with pytest.raises(AnalysisValidationError, match="analytical_fingerprint"):
            validate_build_for_analysis(a_built_suite)

    def test_tampered_raw_source_is_detected_and_refused(
        self, isolated_suite: tuple[str, Path, Path], a_built_suite: str
    ) -> None:
        """Phase 6 gate C, exercised through the analysis layer's own
        validation entry point (not just the lower-level
        verify_build_sources) - the analysis layer must never analyze a
        build whose raw sources changed after that build ran."""
        import pandas as pd

        _suite_id, _operational_dir, _manifest_dir = isolated_suite
        manifest = load_build_manifest(a_built_suite)
        source_path = Path(str(manifest.sources[0]["source_path"]))
        table_path = source_path / "customers.parquet"
        original_bytes = table_path.read_bytes()
        try:
            df = pd.read_parquet(table_path)
            df.loc[df.index[0], "customer_id"] = "CUS_tampered_for_analysis_validation_test"
            df.to_parquet(table_path, index=False)

            with pytest.raises(AnalysisValidationError, match="raw source integrity"):
                validate_build_for_analysis(a_built_suite)
        finally:
            table_path.write_bytes(original_bytes)

        # Restored - validates cleanly again.
        validate_build_for_analysis(a_built_suite)
