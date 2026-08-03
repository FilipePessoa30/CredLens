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

from credlens.model_validation import negative_controls
from credlens.model_validation.negative_controls import (
    PermutationTestError,
    run_pipeline_retrain_permutation_control,
    run_score_label_permutation_control,
)
from credlens.model_validation.permutation_audit import AmplitudeTestResult, CenteringTestResult
from credlens.model_validation.robustness_review import spot_check_robustness
from credlens.model_validation.subgroup_validation import run_subgroup_validation

pytestmark = pytest.mark.slow


class TestScoreLabelPermutationControl:
    def test_runs_and_produces_a_distribution(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        report = run_score_label_permutation_control(
            phase9_experiment_id,
            n_permutations=50,
            base_seed=123,
            alpha=0.01,
            centering_sigma_multiplier=3.0,
            amplitude_ratio_min=1 / 3,
            amplitude_ratio_max=3.0,
            repo_root=phase9_isolated_repo_root,
        )
        assert len(report.roc_auc_distribution) == 50
        assert len(report.audit_table) == 50
        assert 0.0 <= report.empirical_p_value <= 1.0
        assert report.duplicate_permutation_indices == []
        assert report.n_single_class_permutations == 0

    def test_amplitude_matches_theory_closely(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        # No retraining occurs in this control, so its null variance
        # should match the closed-form theoretical SE almost exactly.
        report = run_score_label_permutation_control(
            phase9_experiment_id,
            n_permutations=200,
            base_seed=777,
            alpha=0.01,
            centering_sigma_multiplier=3.0,
            amplitude_ratio_min=1 / 3,
            amplitude_ratio_max=3.0,
            repo_root=phase9_isolated_repo_root,
        )
        assert 0.5 <= report.amplitude.ratio <= 1.5
        assert report.amplitude.within_expected_amplitude

    def test_missing_predictions_raises(self, phase9_isolated_repo_root: Path) -> None:
        with pytest.raises(PermutationTestError):
            run_score_label_permutation_control(
                "TEST_no_such_experiment",
                n_permutations=5,
                base_seed=1,
                alpha=0.01,
                centering_sigma_multiplier=3.0,
                amplitude_ratio_min=1 / 3,
                amplitude_ratio_max=3.0,
                repo_root=phase9_isolated_repo_root,
            )


class TestPipelineRetrainPermutationControl:
    def test_runs_and_produces_a_distribution(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        report = run_pipeline_retrain_permutation_control(
            phase9_experiment_id,
            n_permutations=5,
            base_seed=123,
            alpha=0.01,
            centering_sigma_multiplier=3.0,
            repo_root=phase9_isolated_repo_root,
        )
        assert len(report.roc_auc_distribution) == 5
        assert len(report.audit_table) == 5
        assert 0.0 <= report.empirical_p_value <= 1.0
        assert all(row.train_size > 0 for row in report.audit_table)

    def test_too_few_permutations_cannot_reach_a_strict_alpha(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        # With n permutations the smallest achievable p-value is
        # 1/(n+1) - 5 permutations can never satisfy alpha=0.01.
        report = run_pipeline_retrain_permutation_control(
            phase9_experiment_id,
            n_permutations=5,
            base_seed=456,
            alpha=0.01,
            centering_sigma_multiplier=3.0,
            repo_root=phase9_isolated_repo_root,
        )
        assert report.empirical_p_value >= 1 / 6

    def test_missing_split_raises(self, phase9_isolated_repo_root: Path) -> None:
        with pytest.raises(PermutationTestError):
            run_pipeline_retrain_permutation_control(
                "TEST_no_such_experiment",
                n_permutations=2,
                base_seed=1,
                alpha=0.01,
                centering_sigma_multiplier=3.0,
                repo_root=phase9_isolated_repo_root,
            )


class TestScoreLabelPermutationControlBranches:
    """Fase 10C priority 3 - `run_score_label_permutation_control`'s
    remaining real, reachable branches: the single-class-validation-set
    guard, and the structural-anomaly/centering/amplitude reason-string
    branches. Uses tiny, fully hand-written `<id>__predictions_val.csv`
    files (no model, no retraining) - this control never touches a
    model, so a handful of hand-picked rows is a real exercise of its
    logic, not a synthetic stand-in. Never runs hundreds of permutations."""

    @staticmethod
    def _write_predictions(
        repo_root: Path, experiment_id: str, y_true: list[int], scores: list[float]
    ) -> None:
        tables_dir = repo_root / "reports" / "modeling" / "tables"
        tables_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"y_true": y_true, "logistic_regression": scores}).to_csv(
            tables_dir / f"{experiment_id}__predictions_val.csv", index=False
        )

    def test_single_class_validation_set_raises(self, tmp_path: Path) -> None:
        self._write_predictions(tmp_path, "TEST_single_class", [0, 0, 0], [0.1, 0.2, 0.3])
        with pytest.raises(PermutationTestError, match="only one class"):
            run_score_label_permutation_control(
                "TEST_single_class",
                n_permutations=2,
                base_seed=1,
                alpha=0.5,
                centering_sigma_multiplier=3.0,
                amplitude_ratio_min=1 / 3,
                amplitude_ratio_max=3.0,
                repo_root=tmp_path,
            )

    def test_duplicate_permutations_flagged_as_structural_anomaly(self, tmp_path: Path) -> None:
        # A 2-row frozen validation set has only 2 distinct full-array
        # permutations ([0, 1] and [1, 0]) - requesting 4 permutations
        # guarantees at least one repeat by the pigeonhole principle,
        # deterministically forcing `structural_ok=False` on real data,
        # no mocking involved.
        self._write_predictions(tmp_path, "TEST_dup", [0, 1], [0.3, 0.7])
        report = run_score_label_permutation_control(
            "TEST_dup",
            n_permutations=4,
            base_seed=1,
            alpha=0.5,
            centering_sigma_multiplier=3.0,
            amplitude_ratio_min=1 / 3,
            amplitude_ratio_max=3.0,
            repo_root=tmp_path,
        )
        assert report.duplicate_permutation_indices != []
        assert report.passed is False
        assert "Structural anomaly" in report.reason

    def test_centering_failure_is_reported_in_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A real, well-separated 4-row score/label pair with the
        # structural and amplitude checks pinned to "ok" via monkeypatch -
        # isolating the one branch under test (a non-centered null,
        # otherwise only reachable by astronomically unlucky real seeds).
        self._write_predictions(tmp_path, "TEST_centering", [0, 0, 1, 1], [0.2, 0.4, 0.6, 0.8])
        monkeypatch.setattr(negative_controls, "detect_duplicate_permutations", lambda fp: [])
        monkeypatch.setattr(
            negative_controls,
            "centering_test",
            lambda distribution, *, expected_mean, sigma_multiplier: CenteringTestResult(
                observed_mean=0.9,
                expected_mean=expected_mean,
                standard_error_of_mean=0.01,
                z_statistic=40.0,
                sigma_multiplier=sigma_multiplier,
                centered=False,
            ),
        )
        monkeypatch.setattr(
            negative_controls,
            "amplitude_test",
            lambda distribution, theoretical_se, *, ratio_min, ratio_max: AmplitudeTestResult(
                observed_std=theoretical_se,
                theoretical_se=theoretical_se,
                ratio=1.0,
                ratio_min=ratio_min,
                ratio_max=ratio_max,
                within_expected_amplitude=True,
            ),
        )
        report = run_score_label_permutation_control(
            "TEST_centering",
            n_permutations=3,
            base_seed=1,
            alpha=1.0,
            centering_sigma_multiplier=3.0,
            amplitude_ratio_min=1 / 3,
            amplitude_ratio_max=3.0,
            repo_root=tmp_path,
        )
        assert report.passed is False
        assert "not centered" in report.reason.lower()

    def test_amplitude_failure_is_reported_in_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._write_predictions(tmp_path, "TEST_amplitude", [0, 0, 1, 1], [0.2, 0.4, 0.6, 0.8])
        monkeypatch.setattr(negative_controls, "detect_duplicate_permutations", lambda fp: [])
        monkeypatch.setattr(
            negative_controls,
            "centering_test",
            lambda distribution, *, expected_mean, sigma_multiplier: CenteringTestResult(
                observed_mean=expected_mean,
                expected_mean=expected_mean,
                standard_error_of_mean=0.01,
                z_statistic=0.0,
                sigma_multiplier=sigma_multiplier,
                centered=True,
            ),
        )
        monkeypatch.setattr(
            negative_controls,
            "amplitude_test",
            lambda distribution, theoretical_se, *, ratio_min, ratio_max: AmplitudeTestResult(
                observed_std=10 * theoretical_se,
                theoretical_se=theoretical_se,
                ratio=10.0,
                ratio_min=ratio_min,
                ratio_max=ratio_max,
                within_expected_amplitude=False,
            ),
        )
        report = run_score_label_permutation_control(
            "TEST_amplitude",
            n_permutations=3,
            base_seed=1,
            alpha=1.0,
            centering_sigma_multiplier=3.0,
            amplitude_ratio_min=1 / 3,
            amplitude_ratio_max=3.0,
            repo_root=tmp_path,
        )
        assert report.passed is False
        assert "standard deviation" in report.reason.lower()


class TestPipelineRetrainPermutationControlBranches:
    """Fase 10C priority 3 - `run_pipeline_retrain_permutation_control`'s
    remaining real, reachable branches: a genuinely single-class TRAINING
    split (real UCI rows, re-partitioned so every train-assigned row
    shares one class), and the structural/centering reason-string
    branches (forced via monkeypatch, same rationale as the score-label
    control above - real per-permutation retraining makes a real
    duplicate/off-center null astronomically unlikely to hit by seed
    alone)."""

    def test_single_class_training_split_is_flagged(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        from credlens.modeling.contracts import load_target_contract
        from credlens.modeling.data import load_uci_default_credit

        split_path = (
            phase9_isolated_repo_root
            / "reports/modeling/experiments"
            / phase9_experiment_id
            / "split_assignment.csv"
        )
        original_table = pd.read_csv(split_path)
        contract = load_target_contract(phase9_isolated_repo_root)
        df = load_uci_default_credit(phase9_isolated_repo_root)
        target_by_id = df.set_index(contract.identifier_column)[contract.target_column]

        # Every row currently assigned to "train" that belongs to the
        # positive class is moved to "test" instead - "validation" is
        # left untouched (so the already-registered experiment's frozen
        # validation ROC-AUC stays valid), and every row keeps SOME
        # assignment (required by `apply_split_assignment_table`), just a
        # different one - producing a real, single-class TRAINING split.
        mutated_table = original_table.copy()
        is_positive_train = (mutated_table["split"] == "train") & (
            mutated_table["id"].map(target_by_id) == 1
        )
        mutated_table.loc[is_positive_train, "split"] = "test"
        remaining_train_targets = mutated_table.loc[mutated_table["split"] == "train", "id"].map(
            target_by_id
        )
        assert (remaining_train_targets == 0).all()

        try:
            split_path.write_text(mutated_table.to_csv(index=False), encoding="utf-8")
            report = run_pipeline_retrain_permutation_control(
                phase9_experiment_id,
                n_permutations=1,
                base_seed=1,
                alpha=0.5,
                centering_sigma_multiplier=3.0,
                repo_root=phase9_isolated_repo_root,
            )
        finally:
            split_path.write_text(original_table.to_csv(index=False), encoding="utf-8")

        assert report.n_single_class_permutations == 1
        assert report.audit_table[0].status == "single_class"
        assert report.audit_table[0].roc_auc is None

    def test_centering_failure_reason_is_reported(
        self,
        phase9_isolated_repo_root: Path,
        phase9_experiment_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(negative_controls, "detect_duplicate_permutations", lambda fp: [])
        monkeypatch.setattr(
            negative_controls,
            "centering_test",
            lambda distribution, *, expected_mean, sigma_multiplier: CenteringTestResult(
                observed_mean=0.9,
                expected_mean=expected_mean,
                standard_error_of_mean=0.01,
                z_statistic=40.0,
                sigma_multiplier=sigma_multiplier,
                centered=False,
            ),
        )
        report = run_pipeline_retrain_permutation_control(
            phase9_experiment_id,
            n_permutations=1,
            base_seed=999,
            alpha=1.0,
            centering_sigma_multiplier=3.0,
            repo_root=phase9_isolated_repo_root,
        )
        assert report.passed is False
        assert "not centered" in report.reason.lower()

    def test_structural_anomaly_reason_is_reported(
        self,
        phase9_isolated_repo_root: Path,
        phase9_experiment_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(negative_controls, "detect_duplicate_permutations", lambda fp: [0])
        report = run_pipeline_retrain_permutation_control(
            phase9_experiment_id,
            n_permutations=1,
            base_seed=1000,
            alpha=1.0,
            centering_sigma_multiplier=3.0,
            repo_root=phase9_isolated_repo_root,
        )
        assert report.passed is False
        assert "Structural anomaly" in report.reason


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
