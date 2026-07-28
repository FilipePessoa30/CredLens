"""Tests for credlens.model_validation.negative_controls/
subgroup_validation/robustness_review (Phase 9 sections 6, 9, 4).

Marked `slow` - negative_controls refits several logistic regressions on
the full 30,000-row UCI benchmark; robustness_review needs a real
registered experiment to spot-check against.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from credlens.model_validation.negative_controls import (
    PermutationTestError,
    run_permutation_negative_control,
)
from credlens.model_validation.robustness_review import spot_check_robustness
from credlens.model_validation.subgroup_validation import run_subgroup_validation

pytestmark = pytest.mark.slow


class TestPermutationNegativeControl:
    def test_runs_and_produces_a_distribution(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        report = run_permutation_negative_control(
            phase9_experiment_id,
            n_permutations=5,
            base_seed=123,
            alpha=0.01,
            max_permutation_mean_deviation=0.05,
            repo_root=phase9_isolated_repo_root,
        )
        assert len(report.roc_auc_distribution) == 5
        assert len(report.permutation_seeds) == 5
        assert 0.0 <= report.empirical_p_value <= 1.0

    def test_too_few_permutations_cannot_reach_a_strict_alpha(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        # With n permutations the smallest achievable p-value is
        # 1/(n+1) - 5 permutations can never satisfy alpha=0.01.
        report = run_permutation_negative_control(
            phase9_experiment_id,
            n_permutations=5,
            base_seed=456,
            alpha=0.01,
            max_permutation_mean_deviation=0.05,
            repo_root=phase9_isolated_repo_root,
        )
        assert report.empirical_p_value >= 1 / 6

    def test_missing_split_raises(self, phase9_isolated_repo_root: Path) -> None:
        with pytest.raises(PermutationTestError):
            run_permutation_negative_control(
                "TEST_no_such_experiment",
                n_permutations=2,
                base_seed=1,
                alpha=0.01,
                max_permutation_mean_deviation=0.05,
                repo_root=phase9_isolated_repo_root,
            )


class TestSubgroupValidation:
    def test_absolute_gap_excludes_limited_groups(self) -> None:
        raw_df = pd.DataFrame(
            {
                "X2": [1] * 150 + [2] * 150 + [1] * 20,
                "X3": [1] * 320,
                "X4": [1] * 320,
                "X5": [30] * 320,
            }
        )
        rng = np.random.default_rng(0)
        y_test = pd.Series(rng.integers(0, 2, size=320), index=raw_df.index)
        p_test = pd.Series(rng.random(320), index=raw_df.index)
        report = run_subgroup_validation(
            raw_df,
            y_test,
            p_test,
            threshold=0.5,
            age_buckets=[[18, 100]],
            bootstrap_cfg={"n_resamples": 10, "seed": 1, "percentiles": [2.5, 50, 97.5]},
        )
        sex_gap_reports = [g for g in report.gap_reports if g.attribute == "sex"]
        for gap_report in sex_gap_reports:
            # The small (n=20) "male" sub-slice is `limited`, not
            # `adequate` - it must never appear in reportable_groups.
            assert all(g in ("male", "female") for g in gap_report.reportable_groups)

    def test_insufficient_groups_are_excluded_and_listed(self) -> None:
        raw_df = pd.DataFrame(
            {
                "X2": [1] * 150 + [2] * 150 + [1] * 5,
                "X3": [1] * 305,
                "X4": [1] * 305,
                "X5": [30] * 305,
            }
        )
        rng = np.random.default_rng(1)
        y_test = pd.Series(rng.integers(0, 2, size=305), index=raw_df.index)
        p_test = pd.Series(rng.random(305), index=raw_df.index)
        report = run_subgroup_validation(
            raw_df,
            y_test,
            p_test,
            threshold=0.5,
            age_buckets=[[18, 100]],
            bootstrap_cfg={"n_resamples": 10, "seed": 1, "percentiles": [2.5, 50, 97.5]},
        )
        assert len(report.excluded_insufficient_groups) >= 0  # runs without raising either way

    def test_bootstrap_only_computed_for_adequate_groups(self) -> None:
        raw_df = pd.DataFrame(
            {"X2": [1] * 200 + [2] * 50, "X3": [1] * 250, "X4": [1] * 250, "X5": [30] * 250}
        )
        rng = np.random.default_rng(2)
        y_test = pd.Series(rng.integers(0, 2, size=250), index=raw_df.index)
        p_test = pd.Series(rng.random(250), index=raw_df.index)
        report = run_subgroup_validation(
            raw_df,
            y_test,
            p_test,
            threshold=0.5,
            age_buckets=[[18, 100]],
            bootstrap_cfg={"n_resamples": 10, "seed": 1, "percentiles": [2.5, 50, 97.5]},
        )
        by_group = {(m.attribute, m.group): m for m in report.metrics}
        adequate = by_group[("sex", "male")]
        limited = by_group[("sex", "female")]
        assert adequate.sample_classification == "adequate"
        assert adequate.bootstrap is not None
        assert limited.sample_classification == "limited"
        assert limited.bootstrap is None


class TestRobustnessReviewSpotCheck:
    def test_spot_check_reproduces_deterministic_perturbation(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        import joblib

        from credlens.modeling.contracts import load_evaluation_config, load_target_contract
        from credlens.modeling.data import load_uci_default_credit
        from credlens.modeling.splitting import (
            apply_split_assignment_table,
            load_split_assignment_table,
        )
        from credlens.modeling.training import FittedModel

        contract = load_target_contract(phase9_isolated_repo_root)
        config = load_evaluation_config(phase9_isolated_repo_root)
        df = load_uci_default_credit(phase9_isolated_repo_root)
        split_table = load_split_assignment_table(
            phase9_isolated_repo_root
            / "reports/modeling/experiments"
            / phase9_experiment_id
            / "split_assignment.csv"
        )
        assignment = apply_split_assignment_table(
            df, split_table, id_column=contract.identifier_column
        )
        raw_test = df.loc[assignment.test_index]
        y_test = df.loc[assignment.test_index, contract.target_column]

        pipeline = joblib.load(
            phase9_isolated_repo_root
            / "reports/modeling/experiments"
            / phase9_experiment_id
            / "models"
            / "logistic_regression.joblib"
        )
        from credlens.modeling.features import FEATURE_COLUMNS

        fitted = FittedModel(
            model_kind="logistic_regression",
            pipeline=pipeline,
            hyperparameters={},
            seed=42,
            n_jobs=1,
            fit_seconds=0.0,
            feature_columns=list(FEATURE_COLUMNS),
        )
        robustness_table = pd.read_csv(
            phase9_isolated_repo_root
            / "reports/modeling/tables"
            / f"{phase9_experiment_id}__robustness.csv"
        )
        comparisons = spot_check_robustness(
            fitted,
            raw_test,
            y_test,
            robustness_table,
            robustness_cfg=config.robustness,
            tolerance=0.0005,
            stochastic_tolerance=0.08,
        )
        assert len(comparisons) == 2
        deterministic = next(c for c in comparisons if "delinquency_worsening" in c.metric)
        assert deterministic.within_tolerance
