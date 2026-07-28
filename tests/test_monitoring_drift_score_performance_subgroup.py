"""Tests for credlens.monitoring.drift/score_monitoring/performance/
subgroup/data_quality (Phase 9 sections 15.1-15.5) - fast, pure-function
tests using small synthetic arrays (no real 30k-row benchmark needed).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from credlens.modeling.input_contract import validate_input_contract
from credlens.monitoring import data_quality, drift, performance, score_monitoring, subgroup


class TestDataQuality:
    def test_clean_batch_is_schema_valid(self) -> None:
        batch = pd.DataFrame({"ID": [1, 2, 3], **{f"X{i}": [1, 2, 3] for i in range(1, 24)}})
        report = validate_input_contract(batch, "audit")
        result = data_quality.compute_data_quality(batch, report)
        assert result.schema_valid is True
        assert result.row_count == 3


class TestDrift:
    def test_psi_is_zero_for_identical_distributions(self) -> None:
        rng = np.random.default_rng(0)
        values = rng.normal(size=1000)
        psi = drift.population_stability_index(
            values, values, bin_edges=list(np.histogram(values, bins=10)[1])
        )
        assert psi == pytest.approx(0.0, abs=1e-6)

    def test_psi_is_positive_for_shifted_distribution(self) -> None:
        rng = np.random.default_rng(1)
        reference = rng.normal(size=1000)
        shifted = rng.normal(loc=3.0, size=1000)
        bin_edges = list(np.histogram(reference, bins=10)[1])
        psi = drift.population_stability_index(reference, shifted, bin_edges)
        assert psi > 0.1

    def test_jensen_shannon_divergence_is_bounded(self) -> None:
        rng = np.random.default_rng(2)
        reference = rng.normal(size=500)
        batch = rng.normal(loc=1.0, size=500)
        bin_edges = list(np.histogram(reference, bins=10)[1])
        jsd = drift.jensen_shannon_divergence(reference, batch, bin_edges)
        assert 0.0 <= jsd <= 1.0

    def test_compute_feature_drift_reports_all_metrics(self) -> None:
        rng = np.random.default_rng(3)
        reference = rng.normal(size=1000)
        batch = rng.normal(loc=0.5, size=200)
        stats = {
            "mean": float(reference.mean()),
            "median": float(np.median(reference)),
            "std": float(reference.std()),
            "missingness": 0.0,
            "quantiles": {"0.5": float(np.median(reference))},
        }
        bin_edges = list(np.histogram(reference, bins=10)[1])
        result = drift.compute_feature_drift("feat", reference, batch, stats, bin_edges)
        assert result.n_batch == 200
        assert result.psi >= 0.0
        assert 0.0 <= result.ks_statistic <= 1.0

    def test_compute_feature_drift_handles_all_nan_batch(self) -> None:
        rng = np.random.default_rng(4)
        reference = rng.normal(size=500)
        batch = np.full(50, np.nan)
        stats = {
            "mean": float(reference.mean()),
            "median": float(np.median(reference)),
            "std": float(reference.std()),
            "missingness": 0.0,
            "quantiles": {"0.5": 0.0},
        }
        bin_edges = list(np.histogram(reference, bins=10)[1])
        result = drift.compute_feature_drift("feat", reference, batch, stats, bin_edges)
        assert result.missingness_delta == pytest.approx(1.0)


class TestScoreMonitoring:
    def test_score_drift_reports_shift_and_bands(self) -> None:
        rng = np.random.default_rng(5)
        reference_scores = rng.uniform(0, 1, size=1000)
        batch_scores = rng.uniform(0.2, 0.8, size=200)
        stats = {
            "mean": float(reference_scores.mean()),
            "histogram": {"bin_edges": list(np.histogram(reference_scores, bins=10)[1])},
            "quantiles": {"0.5": float(np.median(reference_scores))},
        }
        result = score_monitoring.compute_score_drift(
            reference_scores,
            batch_scores,
            reference_score_stats=stats,
            risk_band_cuts=[0.25, 0.5, 0.75],
            reference_risk_band_distribution={
                "low": 0.25,
                "medium": 0.25,
                "high": 0.25,
                "very_high": 0.25,
            },
            top10_threshold=0.9,
        )
        assert result.n_batch == 200
        assert set(result.risk_band_distribution.keys()) <= {"low", "medium", "high", "very_high"}

    def test_rank_stability_computed_when_twin_provided(self) -> None:
        rng = np.random.default_rng(6)
        reference_scores = rng.uniform(size=500)
        batch_scores = rng.uniform(size=50)
        twin = batch_scores + rng.normal(scale=0.01, size=50)
        stats = {
            "mean": float(reference_scores.mean()),
            "histogram": {"bin_edges": list(np.histogram(reference_scores, bins=10)[1])},
            "quantiles": {"0.5": 0.5},
        }
        result = score_monitoring.compute_score_drift(
            reference_scores,
            batch_scores,
            reference_score_stats=stats,
            risk_band_cuts=[0.25, 0.5, 0.75],
            reference_risk_band_distribution={
                "low": 0.25,
                "medium": 0.25,
                "high": 0.25,
                "very_high": 0.25,
            },
            top10_threshold=0.9,
            baseline_scores_same_rows=twin,
        )
        assert result.rank_stability_spearman is not None
        assert result.rank_stability_spearman > 0.9


class TestPerformance:
    def test_performance_drift_reports_deltas(self) -> None:
        rng = np.random.default_rng(7)
        y = pd.Series(rng.integers(0, 2, size=300))
        p = pd.Series(rng.random(300))
        result = performance.compute_performance_drift(
            y,
            p,
            threshold=0.5,
            reference_roc_auc=0.6,
            reference_pr_auc=0.3,
            reference_brier=0.2,
            n_bootstrap=20,
        )
        assert result.n_rows == 300
        assert result.roc_auc_delta == pytest.approx(result.roc_auc - 0.6)

    def test_single_class_batch_raises(self) -> None:
        y = pd.Series([1, 1, 1])
        p = pd.Series([0.5, 0.6, 0.7])
        with pytest.raises(ValueError):
            performance.compute_performance_drift(
                y,
                p,
                threshold=0.5,
                reference_roc_auc=0.6,
                reference_pr_auc=0.3,
                reference_brier=0.2,
            )


class TestSubgroupMonitoring:
    def test_composition_and_selection_rate_reported(self) -> None:
        batch_df = pd.DataFrame({"sex": ["male"] * 60 + ["female"] * 40})
        scores = np.concatenate([np.full(60, 0.8), np.full(40, 0.2)])
        results = subgroup.compute_subgroup_monitoring(
            batch_df,
            scores,
            threshold=0.5,
            reference_composition={"sex": {"male": 500, "female": 500}},
            y_batch=None,
        )
        by_group = {r.group: r for r in results}
        assert by_group["male"].selection_rate == pytest.approx(1.0)
        assert by_group["female"].selection_rate == pytest.approx(0.0)
        assert by_group["male"].composition_share == pytest.approx(0.6)
