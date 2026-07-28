"""Tests for credlens.model_validation.evidence/recomputation/
discrimination/calibration/thresholds/stability (Phase 9 sections 4, 5,
11) - evidence freezing, and independent recomputation against it.

Marked `slow` - needs the full registered-model pipeline from
`phase9_isolated_repo_root`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from credlens.model_validation import calibration, discrimination, stability, thresholds
from credlens.model_validation.evidence import (
    EvidenceError,
    freeze_evidence,
    load_evidence,
    load_validation_config,
    write_evidence,
)
from credlens.model_validation.recomputation import RecomputationError, run_recomputation

pytestmark = pytest.mark.slow


class TestFreezeEvidence:
    def test_freezes_hashes_and_metrics(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        evidence = freeze_evidence(
            phase9_experiment_id, "some_model", repo_root=phase9_isolated_repo_root
        )
        assert evidence.experiment_id == phase9_experiment_id
        assert len(evidence.dataset_hash) == 64
        assert len(evidence.train_id_hash) == 64
        assert evidence.original_test_metrics["discrimination"]["roc_auc"] > 0.5

    def test_write_and_load_roundtrip(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        evidence = freeze_evidence(
            phase9_experiment_id, "some_model", repo_root=phase9_isolated_repo_root
        )
        write_evidence(evidence, repo_root=phase9_isolated_repo_root)
        loaded = load_evidence(phase9_experiment_id, repo_root=phase9_isolated_repo_root)
        assert loaded.dataset_hash == evidence.dataset_hash

    def test_missing_experiment_raises(self, phase9_isolated_repo_root: Path) -> None:
        with pytest.raises(EvidenceError):
            freeze_evidence("TEST_does_not_exist", repo_root=phase9_isolated_repo_root)

    def test_load_missing_evidence_raises(self, phase9_isolated_repo_root: Path) -> None:
        with pytest.raises(EvidenceError):
            load_evidence("TEST_never_frozen", repo_root=phase9_isolated_repo_root)


class TestRunRecomputation:
    def test_recomputation_matches_frozen_evidence(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        evidence = freeze_evidence(phase9_experiment_id, "m", repo_root=phase9_isolated_repo_root)
        cfg = load_validation_config(phase9_isolated_repo_root)
        tolerance = float(cfg.recomputation["metric_absolute_tolerance"])
        op_tolerance = float(cfg.recomputation["operating_point_tolerance"])
        report = run_recomputation(
            evidence,
            tolerance,
            operating_point_tolerance=op_tolerance,
            repo_root=phase9_isolated_repo_root,
        )
        assert report.all_passed is True
        for comparison in report.discrimination_comparisons:
            assert comparison.within_tolerance

    def test_missing_tables_raise(self, phase9_isolated_repo_root: Path) -> None:
        from credlens.model_validation.evidence import EvidenceManifest

        fake = EvidenceManifest(
            experiment_id="TEST_missing_tables",
            model_id=None,
            dataset_id="uci-default-credit",
            dataset_hash="a" * 64,
            split_hash="b" * 64,
            train_id_hash="c" * 64,
            validation_id_hash="d" * 64,
            test_id_hash="e" * 64,
            feature_registry_version="1.0.0",
            config_hash="f" * 64,
            prediction_hash="g" * 64,
            target_hash="h" * 64,
            artifact_hash=None,
            dependency_versions={},
            original_test_metrics={},
            code_version="0.0.0",
        )
        with pytest.raises(RecomputationError):
            run_recomputation(fake, 0.001, repo_root=phase9_isolated_repo_root)


class TestIndependentDiscrimination:
    def test_roc_auc_matches_perfect_separation(self) -> None:
        y = pd.Series([0, 0, 1, 1])
        p = pd.Series([0.1, 0.2, 0.8, 0.9])
        assert discrimination.independent_roc_auc(y, p) == pytest.approx(1.0)

    def test_roc_auc_matches_sklearn(self) -> None:
        from sklearn.metrics import roc_auc_score

        rng = np.random.default_rng(0)
        y = pd.Series(rng.integers(0, 2, size=200))
        p = pd.Series(rng.random(200))
        assert discrimination.independent_roc_auc(y, p) == pytest.approx(
            roc_auc_score(y, p), abs=1e-9
        )

    def test_pr_auc_matches_sklearn(self) -> None:
        from sklearn.metrics import average_precision_score

        rng = np.random.default_rng(1)
        y = pd.Series(rng.integers(0, 2, size=200))
        p = pd.Series(rng.random(200))
        assert discrimination.independent_pr_auc(y, p) == pytest.approx(
            average_precision_score(y, p), abs=1e-9
        )

    def test_roc_auc_raises_with_one_class(self) -> None:
        with pytest.raises(discrimination.DiscriminationValidationError):
            discrimination.independent_roc_auc(pd.Series([1, 1, 1]), pd.Series([0.1, 0.2, 0.3]))

    def test_ks_statistic_is_bounded(self) -> None:
        rng = np.random.default_rng(2)
        y = pd.Series(rng.integers(0, 2, size=200))
        p = pd.Series(rng.random(200))
        ks = discrimination.independent_ks_statistic(y, p)
        assert 0.0 <= ks <= 1.0


class TestIndependentCalibration:
    def test_brier_matches_sklearn(self) -> None:
        from sklearn.metrics import brier_score_loss

        rng = np.random.default_rng(3)
        y = pd.Series(rng.integers(0, 2, size=200))
        p = pd.Series(rng.random(200))
        assert calibration.independent_brier(y, p) == pytest.approx(
            brier_score_loss(y, p), abs=1e-9
        )

    def test_perfectly_calibrated_slope_is_near_one(self) -> None:
        rng = np.random.default_rng(4)
        p = pd.Series(rng.uniform(0.05, 0.95, size=5000))
        y = pd.Series((rng.random(5000) < p).astype(int))
        intercept, slope = calibration.independent_calibration_slope_intercept(y, p)
        assert slope == pytest.approx(1.0, abs=0.15)
        assert intercept == pytest.approx(0.0, abs=0.15)

    def test_ece_bin_sensitivity_runs_both_strategies(self) -> None:
        rng = np.random.default_rng(5)
        y = pd.Series(rng.integers(0, 2, size=300))
        p = pd.Series(rng.random(300))
        results = calibration.ece_bin_sensitivity(y, p, bin_counts=[5, 10])
        strategies = {r.strategy for r in results}
        assert strategies == {"equal_width", "equal_mass"}


class TestIndependentThresholds:
    def test_confusion_counts_match_expected(self) -> None:
        y = pd.Series([0, 0, 1, 1])
        p = pd.Series([0.1, 0.6, 0.4, 0.9])
        counts = thresholds.independent_confusion_counts(y, p, 0.5)
        assert counts.true_positive == 1
        assert counts.false_positive == 1
        assert counts.true_negative == 1
        assert counts.false_negative == 1

    def test_population_share_threshold_selects_correct_count(self) -> None:
        p = pd.Series(np.arange(100) / 100.0)
        threshold = thresholds.independent_threshold_for_population_share(p, 0.1)
        assert (p >= threshold).sum() == 10

    def test_threshold_determinism(self) -> None:
        p = pd.Series(np.linspace(0, 1, 500))
        t1 = thresholds.independent_threshold_for_population_share(p, 0.2)
        t2 = thresholds.independent_threshold_for_population_share(p, 0.2)
        assert t1 == t2

    def test_population_share_threshold_stability_is_bounded(self) -> None:
        rng = np.random.default_rng(6)
        p = pd.Series(rng.random(1000))
        values = thresholds.population_share_threshold_stability(p, 0.1, n_trials=5)
        assert len(values) == 5
        assert max(values) - min(values) < 0.2


class TestSplitStabilityRecomputation:
    def test_recomputes_mean_and_stdev(self) -> None:
        table = pd.DataFrame(
            {"roc_auc": [0.7, 0.72, 0.71, 0.69, 0.73], "pr_auc": [0.5, 0.51, 0.49, 0.5, 0.52]}
        )
        original = {
            "roc_auc_mean": float(table["roc_auc"].mean()),
            "roc_auc_stdev": float(table["roc_auc"].std(ddof=1)),
            "pr_auc_mean": float(table["pr_auc"].mean()),
            "pr_auc_stdev": float(table["pr_auc"].std(ddof=1)),
        }
        result = stability.recompute_split_stability(table, original, tolerance=1e-9)
        assert all(c.within_tolerance for c in result.comparisons)

    def test_needs_at_least_two_seeds(self) -> None:
        table = pd.DataFrame({"roc_auc": [0.7], "pr_auc": [0.5]})
        with pytest.raises(ValueError):
            stability.recompute_split_stability(table, {}, tolerance=0.01)
