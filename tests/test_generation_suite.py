"""Tests for credlens.generation.suite: generate_suite() ties a baseline
run to its CRN scenario runs, and the suite manifest records what
common-random-numbers actually held (Phase 4B sections 5, 16)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.generation.config import CRN_SCENARIOS, load_generation_config
from credlens.generation.suite import SuiteError, generate_suite, load_suite_manifest

_SEED = 313_131


@pytest.fixture
def cleanup_suite() -> Iterator[None]:
    yield
    config = load_generation_config()
    for base in (config.output.operational_dir, config.output.truth_dir):
        base_path = Path(base)
        if not base_path.is_dir():
            continue
        for run_dir in base_path.iterdir():
            if str(_SEED) in run_dir.name:
                shutil.rmtree(run_dir)
    manifest_path = Path("reports/synthetic_validation/suites") / f"SUITE_smoke_{_SEED}.json"
    if manifest_path.is_file():
        manifest_path.unlink()


class TestGenerateSuite:
    def test_generates_baseline_and_every_crn_scenario(self, cleanup_suite: None) -> None:
        outcome = generate_suite(scale_name="smoke", seed=_SEED, force=True)

        assert outcome.suite_id == f"SUITE_smoke_{_SEED}"
        assert "baseline" in outcome.outcomes
        assert set(outcome.scenario_run_ids) == set(CRN_SCENARIOS)
        for run_outcome in outcome.outcomes.values():
            assert run_outcome.status == "completed"

    def test_population_crn_preserved_for_every_scenario(self, cleanup_suite: None) -> None:
        outcome = generate_suite(scale_name="smoke", seed=_SEED, force=True)
        for scenario, report in outcome.manifest["scenarios"].items():  # type: ignore[attr-defined]
            assert report["population_crn_preserved"] is True, scenario

    def test_directional_checks_all_pass(self, cleanup_suite: None) -> None:
        outcome = generate_suite(scale_name="smoke", seed=_SEED, force=True)
        for scenario, report in outcome.manifest["scenarios"].items():  # type: ignore[attr-defined]
            for check in report["directional_checks"]:
                assert check["passed"] is True, (scenario, check)

    def test_manifest_written_and_loadable(self, cleanup_suite: None) -> None:
        outcome = generate_suite(scale_name="smoke", seed=_SEED, force=True)
        assert outcome.manifest_path.is_file()
        loaded = load_suite_manifest(outcome.suite_id)
        assert loaded["suite_id"] == outcome.suite_id
        assert loaded["baseline_run_id"] == outcome.baseline_run_id

    def test_load_missing_suite_raises(self) -> None:
        with pytest.raises(SuiteError, match="No suite manifest"):
            load_suite_manifest("SUITE_does_not_exist_9999")
