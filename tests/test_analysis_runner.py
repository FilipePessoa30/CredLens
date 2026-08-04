"""Tests for credlens.analysis.runner (Phase 6 sections 8, 18, 21):
`run_analysis()` must produce the full report tree from a real build,
refuse a non-suite build, tolerate a chart failure without aborting the
whole run, and - the mandatory reproducibility proof - running the same
analysis twice from the same build_id must produce byte-identical table
and figure content hashes (never a real institution's confidence
interval-grade "close enough", an exact match)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.analysis.runner import AnalysisRunError, run_analysis
from credlens.generation.orchestrator import generate_scenario
from credlens.generation.suite import generate_suite
from credlens.generation.testing_support import (
    isolated_manifest_dir,
    isolated_output_dirs,
    safe_rmtree,
)
from credlens.warehouse.build import _rmtree_with_retry, build_dir_for, run_build

# Fase 11B - see tests/test_warehouse_build.py's own comment: this file
# was never marked slow, causing the dedicated CI job's slow-test step
# to exit 5 ("no tests collected").
pytestmark = pytest.mark.slow

_SEED = 703_504
_BUILD_ID = "BUILD_pytest_analysis_runner"
_SINGLE_RUN_BUILD_ID = "BUILD_pytest_analysis_runner_single"


@pytest.fixture(scope="module")
def isolated_suite(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path, Path]]:
    tmp_path = tmp_path_factory.mktemp("analysis_runner")
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


class TestRunAnalysisProducesTheFullReportTree:
    def test_writes_every_expected_file(self, a_built_suite: str, tmp_path: Path) -> None:
        output_dir = tmp_path / "report"
        result = run_analysis(
            build_id=a_built_suite, output_dir=output_dir, include_benchmark=False
        )

        assert result.manifest.final_status in ("success", "completed_with_warnings")
        assert result.executive_summary_en.is_file()
        assert result.executive_summary_pt.is_file()
        assert result.technical_report_en.is_file()
        assert result.technical_report_pt.is_file()
        assert result.manifest_path.is_file()
        assert len(result.manifest.tables_written) >= 10
        assert len(result.manifest.figures_written) >= 8

    def test_reports_are_always_hashed_into_the_manifest(
        self, a_built_suite: str, tmp_path: Path
    ) -> None:
        """Phase 7 gate E: executive/technical reports get a content hash
        unconditionally (not opt-in like --multiseed/--insights) - a
        previous "identical" run could silently diverge in prose while
        every table/figure hash still matched."""
        output_dir = tmp_path / "report_hashes"
        result = run_analysis(
            build_id=a_built_suite, output_dir=output_dir, include_benchmark=False
        )
        for name in (
            "executive_summary_en",
            "executive_summary_pt",
            "technical_report_en",
            "technical_report_pt",
        ):
            assert name in result.manifest.reports_written
            assert result.manifest.reports_written[name] != "missing"

    def test_insights_registry_is_generated_and_hashed_when_requested(
        self, a_built_suite: str, tmp_path: Path
    ) -> None:
        """Phase 7 gate D+E: --insights writes insights.yml and hashes it
        into the same reproducibility fingerprint as everything else."""
        output_dir = tmp_path / "report_insights"
        result = run_analysis(
            build_id=a_built_suite,
            output_dir=output_dir,
            include_benchmark=False,
            include_insights=True,
        )
        assert (output_dir / "insights.yml").is_file()
        assert "insights_registry" in result.manifest.reports_written
        assert result.manifest.reports_written["insights_registry"] != "missing"
        assert not result.manifest.warnings

    def test_insights_registry_content_fingerprint_matches_across_two_runs(
        self, a_built_suite: str, tmp_path: Path
    ) -> None:
        """Phase 7 gate E regression: two independent run_analysis() calls
        against the SAME build get different analysis_id values (fresh
        timestamp each time, by design) - the insights_registry entry in
        reports_written must still match, because it is a content
        fingerprint (credlens.analysis.insights.content_fingerprint), not
        a raw file hash of a file that embeds analysis_id."""
        first = run_analysis(
            build_id=a_built_suite,
            output_dir=tmp_path / "insights_run_1",
            include_benchmark=False,
            include_insights=True,
        )
        second = run_analysis(
            build_id=a_built_suite,
            output_dir=tmp_path / "insights_run_2",
            include_benchmark=False,
            include_insights=True,
        )
        assert first.analysis_id != second.analysis_id
        assert (
            first.manifest.reports_written["insights_registry"]
            == second.manifest.reports_written["insights_registry"]
        )

    def test_insights_registry_is_absent_by_default(
        self, a_built_suite: str, tmp_path: Path
    ) -> None:
        output_dir = tmp_path / "report_no_insights"
        result = run_analysis(
            build_id=a_built_suite, output_dir=output_dir, include_benchmark=False
        )
        assert not (output_dir / "insights.yml").is_file()
        assert "insights_registry" not in result.manifest.reports_written

    def test_benchmark_figure_is_included_when_requested(
        self, a_built_suite: str, tmp_path: Path
    ) -> None:
        output_dir = tmp_path / "report_benchmark"
        result = run_analysis(build_id=a_built_suite, output_dir=output_dir, include_benchmark=True)
        assert "public_benchmark_overview" in result.manifest.figures_written
        assert (output_dir / "figures" / "public_benchmark_overview.png").is_file()

    def test_multiseed_summary_and_figure_are_included_when_requested(
        self, a_built_suite: str, tmp_path: Path
    ) -> None:
        from credlens.generation.config import config_path_for_scenario, load_generation_config
        from credlens.generation.manifest import canonical_config_hash
        from credlens.generation.orchestrator import _compute_generation_run_id
        from credlens.generation.testing_support import delete_exact_run_dir

        # run_analysis() has no multiseed-start-seed override of its own -
        # it always delegates to robustness_across_seeds()'s own default
        # (970_001, itself chosen to never collide with an official
        # demo run/suite - see multiseed.py). Cleanup below targets that
        # same default seed pair for exactly that reason.
        start_seed = 970_001
        output_dir = tmp_path / "report_multiseed"
        try:
            result = run_analysis(
                build_id=a_built_suite,
                output_dir=output_dir,
                include_benchmark=False,
                include_multiseed=True,
                multiseed_seeds=2,
                multiseed_scenario="macroeconomic_stress",
                multiseed_scale="smoke",
            )
            assert "multiseed_stability" in result.manifest.figures_written
            assert (output_dir / "figures" / "multiseed_stability.png").is_file()
            manifest_json = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            assert manifest_json["parameters"]["include_multiseed"] is True
        finally:
            baseline_hash = canonical_config_hash(load_generation_config())
            stress_hash = canonical_config_hash(
                load_generation_config(config_path_for_scenario("macroeconomic_stress"))
            )
            scenario_hashes = (("baseline", baseline_hash), ("macroeconomic_stress", stress_hash))
            seeds = (start_seed, start_seed + 1)
            run_ids = [
                _compute_generation_run_id(scenario, "smoke", seed, config_hash)
                for seed in seeds
                for scenario, config_hash in scenario_hashes
            ]
            config = load_generation_config()
            for base in (config.output.operational_dir, config.output.truth_dir):
                for run_id in run_ids:
                    delete_exact_run_dir(Path(base), run_id)

            # generate_suite() (called once per seed by run_monte_carlo)
            # also writes a suite manifest to the shared
            # reports/synthetic_validation/suites/ directory by default -
            # a real, previously-undetected gap (see
            # tests/test_analysis_multiseed.py's identical fix). Delete
            # only the exact, uniquely-seeded files this test created.
            suites_dir = Path("reports/synthetic_validation/suites")
            for seed in seeds:
                manifest_path = suites_dir / f"SUITE_smoke_{seed}.json"
                manifest_path.unlink(missing_ok=True)

    def test_all_recorded_table_and_figure_hashes_match_real_files(
        self, a_built_suite: str, tmp_path: Path
    ) -> None:
        import hashlib

        output_dir = tmp_path / "report2"
        result = run_analysis(
            build_id=a_built_suite, output_dir=output_dir, include_benchmark=False
        )

        for name, recorded_hash in result.manifest.tables_written.items():
            path = output_dir / "tables" / f"{name}.csv"
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == recorded_hash

        for name, recorded_hash in result.manifest.figures_written.items():
            path = output_dir / "figures" / f"{name}.png"
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == recorded_hash

    def test_executive_summaries_reference_the_build_and_suite(
        self, a_built_suite: str, tmp_path: Path
    ) -> None:
        output_dir = tmp_path / "report3"
        result = run_analysis(
            build_id=a_built_suite, output_dir=output_dir, include_benchmark=False
        )
        text = result.executive_summary_en.read_text(encoding="utf-8")
        assert a_built_suite in text


class TestRunAnalysisRejectsANonSuiteBuild:
    @pytest.fixture(scope="class")
    def a_built_single_run(self, tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
        tmp_path = tmp_path_factory.mktemp("analysis_runner_single")
        operational_dir, truth_dir = isolated_output_dirs(tmp_path)
        from credlens.generation.config import (
            DEFAULT_CONFIG_PATH,
            load_generation_config,
            with_output_dirs,
        )

        config = with_output_dirs(
            load_generation_config(DEFAULT_CONFIG_PATH),
            operational_dir=operational_dir,
            truth_dir=truth_dir,
        )
        outcome = generate_scenario(
            scenario="baseline",
            scale_name="smoke",
            seed=_SEED + 1,
            force=True,
            config_override=config,
        )
        manifest = run_build(
            run_id=outcome.generation_run_id,
            build_id=_SINGLE_RUN_BUILD_ID,
            force=True,
            operational_root=operational_dir,
        )
        assert manifest.final_status == "success"
        yield manifest.build_id
        build_dir = build_dir_for(_SINGLE_RUN_BUILD_ID)
        if build_dir.exists():
            try:
                _rmtree_with_retry(build_dir)
            except PermissionError:
                shutil.rmtree(build_dir, ignore_errors=True)
        safe_rmtree(tmp_path, allowed_root=tmp_path)

    def test_raises_analysis_run_error(self, a_built_single_run: str, tmp_path: Path) -> None:
        with pytest.raises(AnalysisRunError, match="suite"):
            run_analysis(build_id=a_built_single_run, output_dir=tmp_path / "report")


class TestRunAnalysisIsReproducible:
    """The mandatory reproducibility proof (Phase 6 sections 21, 26):
    running the same analysis twice, from the same build_id, must produce
    identical table/figure content hashes - not merely similar output."""

    def test_two_runs_from_the_same_build_produce_identical_content_hashes(
        self, a_built_suite: str, tmp_path: Path
    ) -> None:
        result1 = run_analysis(
            build_id=a_built_suite, output_dir=tmp_path / "run1", include_benchmark=False
        )
        result2 = run_analysis(
            build_id=a_built_suite, output_dir=tmp_path / "run2", include_benchmark=False
        )

        assert result1.manifest.tables_written == result2.manifest.tables_written
        assert result1.manifest.figures_written == result2.manifest.figures_written
        assert set(result1.manifest.tables_written) == set(result2.manifest.tables_written)
        assert len(result1.manifest.tables_written) > 0

    def test_report_text_content_is_identical_across_runs(
        self, a_built_suite: str, tmp_path: Path
    ) -> None:
        result1 = run_analysis(
            build_id=a_built_suite, output_dir=tmp_path / "run3", include_benchmark=False
        )
        result2 = run_analysis(
            build_id=a_built_suite, output_dir=tmp_path / "run4", include_benchmark=False
        )
        assert result1.executive_summary_en.read_text(
            encoding="utf-8"
        ) == result2.executive_summary_en.read_text(encoding="utf-8")
        assert result1.technical_report_pt.read_text(
            encoding="utf-8"
        ) == result2.technical_report_pt.read_text(encoding="utf-8")
