"""Tests for credlens.analysis.multiseed (Phase 6 section 13): a real,
cheap (2-seed, smoke-scale) robustness sweep - never labeled a
statistical confidence interval. `robustness_across_seeds` delegates to
`credlens.generation.montecarlo.run_monte_carlo` (Phase 4B), which writes
into the SHARED data/synthetic/ root (no isolated-root override exists
for it yet) - exactly like `tests/test_cli_synthetic_4b.py`'s own
monte-carlo test, so this file follows that same established pattern:
pick a start_seed far outside any official demonstration seed (Phase 6
gate B), then delete ONLY the exact run directories this test's own call
created (never a substring match)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.analysis.multiseed import RobustnessSummary, robustness_across_seeds
from credlens.generation.config import config_path_for_scenario, load_generation_config
from credlens.generation.manifest import canonical_config_hash
from credlens.generation.orchestrator import _compute_generation_run_id
from credlens.generation.testing_support import delete_exact_run_dir

_START_SEED = 960_501  # never used by any official demo run/suite or other test
_SEEDS = (_START_SEED, _START_SEED + 1)


@pytest.fixture
def cleanup_multiseed_runs() -> Iterator[None]:
    yield
    baseline_hash = canonical_config_hash(load_generation_config())
    stress_hash = canonical_config_hash(
        load_generation_config(config_path_for_scenario("macroeconomic_stress"))
    )
    scenario_hashes = (("baseline", baseline_hash), ("macroeconomic_stress", stress_hash))
    run_ids = [
        _compute_generation_run_id(scenario, "smoke", seed, config_hash)
        for seed in _SEEDS
        for scenario, config_hash in scenario_hashes
    ]
    config = load_generation_config()
    for base in (config.output.operational_dir, config.output.truth_dir):
        for run_id in run_ids:
            delete_exact_run_dir(Path(base), run_id)

    # generate_suite() (called once per seed by run_monte_carlo) also
    # writes a suite manifest to the shared reports/synthetic_validation/
    # suites/ directory by default (Phase 4B never exposed a manifest_dir
    # override to run_monte_carlo/robustness_across_seeds) - a real,
    # previously-undetected gap: no existing monte-carlo test cleaned
    # this file up. Delete only the exact, uniquely-seeded files this
    # test's own call created - never a directory-wide cleanup.
    suites_dir = Path("reports/synthetic_validation/suites")
    for seed in _SEEDS:
        manifest_path = suites_dir / f"SUITE_smoke_{seed}.json"
        manifest_path.unlink(missing_ok=True)


class TestRobustnessAcrossSeeds:
    def test_runs_two_seeds_at_smoke_scale_and_returns_a_summary(
        self, cleanup_multiseed_runs: None
    ) -> None:
        result = robustness_across_seeds("macroeconomic_stress", "smoke", 2, start_seed=_START_SEED)
        assert isinstance(result, RobustnessSummary)
        assert result.scenario == "macroeconomic_stress"
        assert result.scale == "smoke"
        assert result.seeds == list(_SEEDS)
        assert result.metric_summaries  # at least one metric compared
        assert all(isinstance(s, int) for s in result.contract_failures)

    def test_metric_summaries_have_the_documented_fields(
        self, cleanup_multiseed_runs: None
    ) -> None:
        result = robustness_across_seeds("macroeconomic_stress", "smoke", 2, start_seed=_START_SEED)
        for _name, summary in result.metric_summaries.items():
            assert "mean_delta" in summary
            assert "stdev_delta" in summary
            assert "min_delta" in summary
            assert "max_delta" in summary
            assert "n_seeds" in summary
            assert summary["n_seeds"] == 2
            assert "fraction_in_expected_direction" in summary
            assert "any_inversion" in summary

    def test_to_dict_is_explicitly_labeled_simulation_variability(
        self, cleanup_multiseed_runs: None
    ) -> None:
        result = robustness_across_seeds("macroeconomic_stress", "smoke", 2, start_seed=_START_SEED)
        d = result.to_dict()
        assert d["label"] == "simulation_variability_across_synthetic_dgp_seeds"
        assert "confidence" not in d["label"]

    def test_default_start_seed_is_never_the_official_demo_seed(self) -> None:
        import inspect

        default_start_seed = (
            inspect.signature(robustness_across_seeds).parameters["start_seed"].default
        )
        assert default_start_seed != 2026
