"""Tests for credlens.generation.montecarlo: multi-seed aggregation and
its documented expected-direction bookkeeping (Phase 4B section 13). Kept
to 2 seeds at 'smoke' scale - fast enough for CI, per section 19."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.generation.config import load_generation_config
from credlens.generation.montecarlo import EXPECTED_DIRECTIONS, run_monte_carlo

_SEEDS = [606_001, 606_002]


@pytest.fixture
def cleanup_seeds() -> Iterator[None]:
    yield
    config = load_generation_config()
    for base in (config.output.operational_dir, config.output.truth_dir):
        base_path = Path(base)
        if not base_path.is_dir():
            continue
        for run_dir in base_path.iterdir():
            if any(str(seed) in run_dir.name for seed in _SEEDS):
                shutil.rmtree(run_dir)


class TestRunMonteCarlo:
    def test_requires_at_least_one_seed(self) -> None:
        with pytest.raises(ValueError, match="at least 1 seed"):
            run_monte_carlo(scenario="policy_expansion", scale_name="smoke", seeds=[])

    def test_aggregates_every_comparable_metric_across_seeds(self, cleanup_seeds: None) -> None:
        result = run_monte_carlo(scenario="policy_expansion", scale_name="smoke", seeds=_SEEDS)

        assert result.seeds == _SEEDS
        assert not result.contract_failures
        assert "approval_rate" in result.metric_summaries
        summary = result.metric_summaries["approval_rate"]
        assert len(summary.deltas) == len(_SEEDS)
        expected = EXPECTED_DIRECTIONS["policy_expansion"]["approval_rate"]
        assert summary.expected_direction == expected
        # policy_expansion's approval_rate is expected to increase in
        # every seed (mathematically guaranteed by the shared score/
        # looser cutoff - see test_generation_scenarios_4b's superset test).
        assert summary.fraction_in_expected_direction == 1.0
        assert summary.mean_delta > 0

    def test_collections_change_cure_rate_increases(self, cleanup_seeds: None) -> None:
        result = run_monte_carlo(scenario="collections_change", scale_name="smoke", seeds=_SEEDS)
        summary = result.metric_summaries["cure_rate"]
        assert summary.expected_direction == "increase"
        assert summary.fraction_in_expected_direction is not None
        assert summary.fraction_in_expected_direction >= 0.5
