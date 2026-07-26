"""Tests for credlens.analysis.robustness (Phase 7 gate A): the
multi-scenario multi-seed sweep that completes Phase 6's multiseed
robustness (which only ever ran macroeconomic_stress) for all four
comparable CRN scenarios. Kept to 2 seeds at 'smoke' scale (fast, per the
same CI-time-budget convention as tests/test_analysis_multiseed.py and
tests/test_generation_montecarlo.py) - the real >= 10-seed x 4-scenario
sweep is a one-time analytical action run separately for the Phase 7
final report, never repeated inside the test suite."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.analysis.robustness import (
    DEFAULT_START_SEED,
    ROBUSTNESS_SCENARIOS,
    MetricRobustness,
    ScenarioRobustnessResult,
    _quantiles,
    full_robustness_sweep,
    run_scenario_robustness,
    write_robustness_report,
)
from credlens.generation.config import config_path_for_scenario, load_generation_config
from credlens.generation.manifest import canonical_config_hash
from credlens.generation.orchestrator import _compute_generation_run_id
from credlens.generation.testing_support import delete_exact_run_dir

_START_SEED = 5_960_001  # never used by any official demo run/suite or other test
_SEEDS = (_START_SEED, _START_SEED + 1)


def _cleanup_seeds(scenarios: tuple[str, ...]) -> None:
    baseline_hash = canonical_config_hash(load_generation_config())
    scenario_hashes = {
        scenario: canonical_config_hash(load_generation_config(config_path_for_scenario(scenario)))
        for scenario in scenarios
    }
    config = load_generation_config()
    run_ids = []
    for seed in _SEEDS:
        run_ids.append(_compute_generation_run_id("baseline", "smoke", seed, baseline_hash))
        for scenario, config_hash in scenario_hashes.items():
            run_ids.append(_compute_generation_run_id(scenario, "smoke", seed, config_hash))
    for base in (config.output.operational_dir, config.output.truth_dir):
        for run_id in run_ids:
            delete_exact_run_dir(Path(base), run_id)

    suites_dir = Path("reports/synthetic_validation/suites")
    for seed in _SEEDS:
        (suites_dir / f"SUITE_smoke_{seed}.json").unlink(missing_ok=True)


@pytest.fixture
def cleanup_macro_stress_runs() -> Iterator[None]:
    yield
    _cleanup_seeds(("macroeconomic_stress",))


@pytest.fixture
def cleanup_policy_expansion_runs() -> Iterator[None]:
    yield
    _cleanup_seeds(("policy_expansion",))


@pytest.fixture
def cleanup_two_scenario_runs() -> Iterator[None]:
    yield
    _cleanup_seeds(("policy_expansion", "collections_change"))


class TestRunScenarioRobustness:
    def test_covers_every_richer_gate_a_metric(self, cleanup_macro_stress_runs: None) -> None:
        result = run_scenario_robustness("macroeconomic_stress", "smoke", list(_SEEDS))
        assert isinstance(result, ScenarioRobustnessResult)
        assert result.scenario == "macroeconomic_stress"
        assert result.seeds == list(_SEEDS)
        for metric in (
            "n_applications",
            "n_approved",
            "n_contracts",
            "n_collection_events",
            "approval_rate",
            "dpd30_plus_rate",
            "dpd90_plus_rate",
            "cure_rate",
            "write_off_rate",
            "total_write_off_amount",
            "total_recovery_amount",
        ):
            assert metric in result.metrics, metric
            assert isinstance(result.metrics[metric], MetricRobustness)

    def test_metric_robustness_has_every_documented_field(
        self, cleanup_macro_stress_runs: None
    ) -> None:
        result = run_scenario_robustness("macroeconomic_stress", "smoke", list(_SEEDS))
        m = result.metrics["dpd90_plus_rate"]
        d = m.to_dict()
        for field_name in (
            "metric",
            "scenario",
            "seeds",
            "baseline_values",
            "scenario_values",
            "delta_absolute_per_seed",
            "delta_relative_per_seed",
            "expected_direction",
            "observed_direction_per_seed",
            "fraction_in_expected_direction",
            "inversions",
            "mean",
            "median",
            "stdev",
            "quantiles",
            "minimum",
            "maximum",
            "n_seeds",
            "warnings",
        ):
            assert field_name in d, field_name
        assert d["n_seeds"] == len(_SEEDS)
        assert set(d["quantiles"]) == {"p10", "p50", "p90"}

    def test_macro_stress_includes_pre_shock_equality(
        self, cleanup_macro_stress_runs: None
    ) -> None:
        result = run_scenario_robustness("macroeconomic_stress", "smoke", list(_SEEDS))
        assert result.pre_shock_equality is not None
        pse = result.pre_shock_equality
        assert pse["n_seeds"] == len(_SEEDS)
        assert pse["seeds_checked"] == list(_SEEDS)
        # The DGP's own documented design guarantee: identical draws
        # before shock_date - should hold exactly at generation layer.
        assert pse["fraction_identical"] == 1.0
        assert pse["max_absolute_delta"] == 0.0

    def test_non_macro_scenario_has_no_pre_shock_equality(
        self, cleanup_policy_expansion_runs: None
    ) -> None:
        result = run_scenario_robustness("policy_expansion", "smoke", list(_SEEDS))
        assert result.pre_shock_equality is None

    def test_policy_expansion_n_contracts_expected_direction_is_increase(
        self, cleanup_policy_expansion_runs: None
    ) -> None:
        result = run_scenario_robustness("policy_expansion", "smoke", list(_SEEDS))
        m = result.metrics["n_contracts"]
        assert m.expected_direction == "increase"
        assert m.fraction_in_expected_direction == 1.0
        assert m.inversions == 0

    def test_never_labeled_a_confidence_interval(self, cleanup_macro_stress_runs: None) -> None:
        result = run_scenario_robustness("macroeconomic_stress", "smoke", list(_SEEDS))
        d = result.to_dict()
        assert "confidence" not in d["label_en"].lower()
        assert "intervalo de confianca" not in d["label_pt_br"].lower()
        assert "sintetico" in d["label_pt_br"].lower() or "sintética" in d["label_pt_br"].lower()


class TestFullRobustnessSweep:
    def test_runs_every_scenario_with_the_same_seed_sequence(
        self, cleanup_two_scenario_runs: None
    ) -> None:
        results = full_robustness_sweep(
            scale_name="smoke",
            n_seeds=2,
            start_seed=_START_SEED,
            scenarios=("policy_expansion", "collections_change"),
        )
        assert set(results) == {"policy_expansion", "collections_change"}
        for scenario, result in results.items():
            assert result.scenario == scenario
            assert result.seeds == list(_SEEDS)

    def test_default_scenarios_are_the_four_comparable_crn_scenarios(self) -> None:
        assert ROBUSTNESS_SCENARIOS == (
            "policy_expansion",
            "policy_tightening",
            "macroeconomic_stress",
            "collections_change",
        )

    def test_default_start_seed_never_collides_with_official_or_phase6_seeds(self) -> None:
        assert DEFAULT_START_SEED not in (2026, 970_001, 960_501)


class TestWriteRobustnessReport:
    def test_writes_valid_json_with_both_labels(
        self, tmp_path: Path, cleanup_policy_expansion_runs: None
    ) -> None:
        import json

        result = run_scenario_robustness("policy_expansion", "smoke", list(_SEEDS))
        out_path = tmp_path / "robustness.json"
        write_robustness_report(out_path, {"policy_expansion": result})
        loaded = json.loads(out_path.read_text(encoding="utf-8"))
        assert loaded["label_en"] == "Variability across synthetic DGP runs"
        assert "policy_expansion" in loaded["scenarios"]


class TestQuantiles:
    def test_empty_list_returns_empty_dict(self) -> None:
        assert _quantiles([]) == {}

    def test_real_values_return_p10_p50_p90(self) -> None:
        result = _quantiles([1.0, 2.0, 3.0, 4.0, 5.0])
        assert set(result) == {"p10", "p50", "p90"}
