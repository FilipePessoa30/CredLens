"""Unit tests for credlens.generation.comparison against a real, small
generated run - avoids re-deriving expected metric values by hand for a
synthetic fixture; the generator's own output is the source of truth
here, this module just re-aggregates it."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.generation.comparison import compare_metrics, compute_metrics
from credlens.generation.config import load_generation_config
from credlens.generation.orchestrator import generate_scenario

_SEED = 717_171


@pytest.fixture(scope="module")
def a_real_run() -> Iterator[Path]:
    outcome = generate_scenario(scenario="baseline", scale_name="smoke", seed=_SEED, force=True)
    yield outcome.operational_dir / "operational"
    config = load_generation_config()
    for base in (config.output.operational_dir, config.output.truth_dir):
        path = Path(base) / outcome.generation_run_id
        if path.exists():
            shutil.rmtree(path)


class TestComputeMetrics:
    def test_metrics_are_internally_consistent(self, a_real_run: Path) -> None:
        metrics = compute_metrics("RUN_test", a_real_run)
        assert 0.0 <= metrics.approval_rate <= 1.0
        assert metrics.n_approved <= metrics.n_decided
        assert metrics.n_contracts <= metrics.n_approved
        assert 0.0 <= metrics.dpd90_plus_rate <= metrics.dpd30_plus_rate <= 1.0
        assert metrics.n_write_offs >= 0

    def test_empty_directory_produces_zeroed_metrics(self, tmp_path: Path) -> None:
        metrics = compute_metrics("RUN_empty", tmp_path)
        assert metrics.n_applications == 0
        assert metrics.approval_rate == 0.0
        assert metrics.n_contracts == 0


class TestCompareMetrics:
    def test_comparing_a_run_against_itself_has_zero_deltas(self, a_real_run: Path) -> None:
        metrics = compute_metrics("RUN_test", a_real_run)
        comparisons = compare_metrics(metrics, metrics)
        assert all(c.delta == 0.0 for c in comparisons)
        assert all(c.baseline_value == c.candidate_value for c in comparisons)
