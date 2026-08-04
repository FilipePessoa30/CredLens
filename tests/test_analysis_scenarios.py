"""Tests for credlens.analysis.scenarios (Phase 6 section 12):
composition-vs-performance must correctly split a policy scenario's
booked population into shared/baseline_only/scenario_only by
application_id, and must refuse scenarios where that split is not
meaningful (baseline, macroeconomic_stress, collections_change all share
the exact same booked population as baseline by CRN design)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.analysis import metrics
from credlens.analysis.scenarios import composition_vs_performance
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

_SEED = 703_503
_BUILD_ID = "BUILD_pytest_analysis_scenarios"


@pytest.fixture(scope="module")
def isolated_suite(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path, Path]]:
    tmp_path = tmp_path_factory.mktemp("analysis_scenarios")
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
def suite_id_and_db(isolated_suite: tuple[str, Path, Path]) -> Iterator[tuple[str, Path]]:
    suite_id, operational_dir, manifest_dir = isolated_suite
    manifest = run_build(
        suite_id=suite_id,
        build_id=_BUILD_ID,
        force=True,
        operational_root=operational_dir,
        manifest_dir=manifest_dir,
    )
    assert manifest.final_status == "success"
    yield suite_id, Path(manifest.db_path)
    build_dir = build_dir_for(_BUILD_ID)
    if build_dir.exists():
        try:
            _rmtree_with_retry(build_dir)
        except PermissionError:
            shutil.rmtree(build_dir, ignore_errors=True)


class TestCompositionVsPerformance:
    @pytest.mark.parametrize("scenario", ["policy_expansion", "policy_tightening"])
    def test_membership_counts_are_internally_consistent(
        self, suite_id_and_db: tuple[str, Path], scenario: str
    ) -> None:
        suite_id, db_path = suite_id_and_db
        with metrics.connect(db_path) as conn:
            result = composition_vs_performance(conn, suite_id, scenario)

        assert result.suite_id == suite_id
        assert result.scenario == scenario
        assert result.shared_booked_count >= 0
        assert result.baseline_only_count >= 0
        assert result.scenario_only_count >= 0
        # At least one of the three groups must be non-empty at smoke
        # scale, or the scenario config did nothing observable.
        assert (
            result.shared_booked_count + result.baseline_only_count + result.scenario_only_count > 0
        )

    def test_low_sample_flag_matches_the_threshold(self, suite_id_and_db: tuple[str, Path]) -> None:
        suite_id, db_path = suite_id_and_db
        with metrics.connect(db_path) as conn:
            result = composition_vs_performance(conn, suite_id, "policy_expansion")
        expected_low_sample = (
            result.shared_booked_count < metrics.MIN_SEGMENT_OBSERVATIONS
            or max(result.baseline_only_count, result.scenario_only_count)
            < metrics.MIN_SEGMENT_OBSERVATIONS
        )
        assert result.low_sample == expected_low_sample

    def test_sample_classification_is_the_least_favorable_of_the_three_counts(
        self, suite_id_and_db: tuple[str, Path]
    ) -> None:
        from credlens.analysis.sample_policy import combine_classifications

        suite_id, db_path = suite_id_and_db
        with metrics.connect(db_path) as conn:
            result = composition_vs_performance(conn, suite_id, "policy_expansion")
        expected = combine_classifications(
            result.shared_booked_count, result.baseline_only_count, result.scenario_only_count
        )
        assert result.sample_classification == expected
        assert result.low_sample == (result.sample_classification == "insufficient")

    def test_unknown_suite_id_raises_no_run_found(self, suite_id_and_db: tuple[str, Path]) -> None:
        _suite_id, db_path = suite_id_and_db
        with (
            metrics.connect(db_path) as conn,
            pytest.raises(ValueError, match="No run found"),
        ):
            composition_vs_performance(conn, "SUITE_does_not_exist", "policy_expansion")

    @pytest.mark.parametrize("scenario", ["baseline", "macroeconomic_stress", "collections_change"])
    def test_non_policy_scenarios_are_rejected(
        self, suite_id_and_db: tuple[str, Path], scenario: str
    ) -> None:
        suite_id, db_path = suite_id_and_db
        with (
            metrics.connect(db_path) as conn,
            pytest.raises(ValueError, match="policy_expansion/policy_tightening"),
        ):
            composition_vs_performance(conn, suite_id, scenario)

    def test_par90_is_a_fraction_between_0_and_1_when_present(
        self, suite_id_and_db: tuple[str, Path]
    ) -> None:
        suite_id, db_path = suite_id_and_db
        with metrics.connect(db_path) as conn:
            result = composition_vs_performance(conn, suite_id, "policy_expansion")
        for par90 in (result.shared_par90, result.marginal_par90):
            if par90 is not None:
                assert 0.0 <= par90 <= 1.0

    def test_to_dict_round_trips_every_field(self, suite_id_and_db: tuple[str, Path]) -> None:
        suite_id, db_path = suite_id_and_db
        with metrics.connect(db_path) as conn:
            result = composition_vs_performance(conn, suite_id, "policy_tightening")
        d = result.to_dict()
        assert d["suite_id"] == suite_id
        assert d["scenario"] == "policy_tightening"
        assert set(d.keys()) == {
            "suite_id",
            "scenario",
            "baseline_run_id",
            "scenario_run_id",
            "shared_booked_count",
            "baseline_only_count",
            "scenario_only_count",
            "shared_par90",
            "marginal_par90",
            "shared_outstanding_balance",
            "marginal_outstanding_balance",
            "low_sample",
            "sample_classification",
        }
