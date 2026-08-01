"""Tests for credlens.model_validation.remediation (Phase 10 gate D) -
the documented feature-selection policy, the mechanical stability-
reduced baseline, the 5-model comparison, and the remediation decision.

Fast tests exercise pure logic (policy loading, mechanical feature-set
derivation, the decision function) with no I/O. Slow tests build real
reduced experiments on the isolated full 30,000-row UCI benchmark
(`phase9_isolated_repo_root`), extending it with the model_validation
prerequisites (`validate_independent`, `register_challenger_experiment`,
`compare_candidates`) `run_remediation` depends on.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from credlens.model_validation.remediation import (
    RemediationComparisonRow,
    RemediationError,
    decide_remediation,
    final_remediated_feature_set,
    load_remediation_policy,
    stability_reduced_feature_set,
)


class TestLoadRemediationPolicy:
    def test_loads_the_real_project_policy(self) -> None:
        policy = load_remediation_policy()
        assert policy["remediation_policy_version"] == "1.0.0"
        assert len(policy["final_remediated_feature_decisions"]) == 18

    def test_raises_when_missing(self, tmp_path: Path) -> None:
        with pytest.raises(RemediationError):
            load_remediation_policy(tmp_path)


class TestFinalRemediatedFeatureSet:
    def test_drops_exactly_the_documented_seven_features(self) -> None:
        policy = load_remediation_policy()
        kept = final_remediated_feature_set(policy)
        assert len(kept) == 11
        for dropped in (
            "consecutive_months_delinquent",
            "total_bill_amount",
            "total_payment_amount",
            "limit_exposure_distance",
            "bill_trend",
            "bill_variability",
            "worst_payment_to_bill_ratio",
        ):
            assert dropped not in kept
        for kept_feature in (
            "months_delinquent_count",
            "avg_bill_amount",
            "avg_payment_amount",
            "utilization_ratio",
        ):
            assert kept_feature in kept

    def test_raises_if_policy_is_missing_a_feature(self) -> None:
        incomplete_policy = {
            "final_remediated_feature_decisions": [
                {"feature": "max_delinquency_status", "action": "keep"}
            ]
        }
        with pytest.raises(RemediationError):
            final_remediated_feature_set(incomplete_policy)


class TestStabilityReducedFeatureSet:
    def test_drops_redundant_and_unstable_direction_only(self) -> None:
        table = pd.DataFrame(
            {
                "feature": [
                    "max_delinquency_status",
                    "months_delinquent_count",
                    "consecutive_months_delinquent",
                    "bill_trend",
                ],
                "category": [
                    "stable_direction",
                    "redundant",
                    "redundant",
                    "unstable_direction",
                ],
            }
        )
        kept = stability_reduced_feature_set(table)
        assert "max_delinquency_status" in kept
        assert "months_delinquent_count" not in kept
        assert "consecutive_months_delinquent" not in kept
        assert "bill_trend" not in kept

    def test_real_original_classification_drops_nine_of_eighteen(self) -> None:
        table = pd.read_csv(
            "reports/model_validation/tables/"
            "EXP_behavioral_default_v1__coefficient_classification.csv"
        )
        kept = stability_reduced_feature_set(table)
        assert len(kept) == 9


def _row(**overrides: object) -> RemediationComparisonRow:
    defaults: dict[str, object] = {
        "model": "test",
        "n_features": 11,
        "pr_auc": 0.50,
        "roc_auc": 0.74,
        "brier_score": 0.14,
        "log_loss": 0.45,
        "ks_statistic": 0.38,
        "calibration_slope": 0.95,
        "max_vif": 5.0,
        "condition_number": 6.0,
        "mean_sign_flip_rate": 0.01,
        "split_stability_roc_auc_stdev": 0.008,
        "bootstrap_roc_auc_width": 0.03,
        "scoring_latency_ms": 2.0,
        "artifact_size_bytes": 3500,
        "reason_code_eligible_features": 9,
        "dropped_features": [],
    }
    defaults.update(overrides)
    return RemediationComparisonRow(**defaults)  # type: ignore[arg-type]


_CFG = {
    "max_vif_action_threshold": 10.0,
    "max_kept_feature_sign_flip_rate": 0.05,
    "max_pr_auc_degradation_vs_v1": 0.02,
    "max_pr_auc_suspicious_improvement_vs_v1": 0.03,
    "max_roc_auc_degradation_vs_v1": 0.02,
    "max_roc_auc_suspicious_improvement_vs_v1": 0.03,
}


class TestDecideRemediation:
    def test_healthy_remediation_is_a_candidate(self) -> None:
        original = _row(model="original logistic (v1)", n_features=18, pr_auc=0.502, roc_auc=0.745)
        final = _row(model="Final remediated (gate D)", pr_auc=0.5016, roc_auc=0.7423)
        decision = decide_remediation(original, final, _CFG)
        assert decision.decision == "remediation_candidate"

    def test_high_vif_is_rejected(self) -> None:
        original = _row(model="original logistic (v1)", pr_auc=0.502, roc_auc=0.745)
        final = _row(
            model="Final remediated (gate D)", pr_auc=0.5016, roc_auc=0.7423, max_vif=500.0
        )
        decision = decide_remediation(original, final, _CFG)
        assert decision.decision == "remediation_rejected"
        assert "VIF" in decision.reason

    def test_high_sign_flip_rate_is_rejected(self) -> None:
        original = _row(model="original logistic (v1)", pr_auc=0.502, roc_auc=0.745)
        final = _row(
            model="Final remediated (gate D)",
            pr_auc=0.5016,
            roc_auc=0.7423,
            mean_sign_flip_rate=0.5,
        )
        decision = decide_remediation(original, final, _CFG)
        assert decision.decision == "remediation_rejected"
        assert "sign-flip" in decision.reason

    def test_implausibly_large_improvement_requires_new_external_validation(self) -> None:
        original = _row(model="original logistic (v1)", pr_auc=0.50, roc_auc=0.74)
        final = _row(model="Final remediated (gate D)", pr_auc=0.60, roc_auc=0.80)
        decision = decide_remediation(original, final, _CFG)
        assert decision.decision == "requires_new_external_validation"

    def test_degradation_beyond_tolerance_is_rejected(self) -> None:
        original = _row(model="original logistic (v1)", pr_auc=0.50, roc_auc=0.74)
        final = _row(model="Final remediated (gate D)", pr_auc=0.40, roc_auc=0.65)
        decision = decide_remediation(original, final, _CFG)
        assert decision.decision == "remediation_rejected"
        assert "degraded" in decision.reason

    def test_never_returns_a_promotion_label(self) -> None:
        allowed = {
            "remediation_candidate",
            "remediation_rejected",
            "requires_new_external_validation",
        }
        original = _row(model="original logistic (v1)", pr_auc=0.50, roc_auc=0.74)
        for final_overrides in (
            {"pr_auc": 0.5016, "roc_auc": 0.7423},
            {"max_vif": 500.0},
            {"pr_auc": 0.60, "roc_auc": 0.80},
            {"pr_auc": 0.40, "roc_auc": 0.65},
        ):
            final = _row(model="Final remediated (gate D)", **final_overrides)
            decision = decide_remediation(original, final, _CFG)
            assert decision.decision in allowed
            assert decision.decision not in ("candidate", "production", "validation_passed")


@pytest.fixture(scope="module")
def remediation_prerequisites_built(
    phase9_isolated_repo_root: Path, phase9_experiment_id: str, phase9_model_id: str
) -> Path:
    """Extends `phase9_isolated_repo_root` with the model_validation
    artifacts `run_remediation` depends on (coefficient classification,
    VIF table, Pareto comparison) - these normally come from `credlens
    model validate-independent` / `register-challenger` /
    `compare-candidates`, none of which the shared fixture runs on its
    own."""
    from credlens.model_validation.reporting import (
        compare_candidates,
        register_challenger_experiment,
        validate_independent,
        write_validation_reports,
    )

    validate_independent(
        phase9_model_id, full_permutations=False, repo_root=phase9_isolated_repo_root
    )
    write_validation_reports(phase9_experiment_id, repo_root=phase9_isolated_repo_root)
    register_challenger_experiment(
        phase9_experiment_id, f"{phase9_model_id}_challenger", repo_root=phase9_isolated_repo_root
    )
    compare_candidates(phase9_experiment_id, repo_root=phase9_isolated_repo_root)
    return phase9_isolated_repo_root


@pytest.mark.slow
class TestRunRemediationIntegration:
    def test_run_remediation_end_to_end(
        self,
        remediation_prerequisites_built: Path,
        phase9_experiment_id: str,
    ) -> None:
        from credlens.model_validation.remediation import run_remediation
        from credlens.modeling.registry import load_experiment

        repo_root = remediation_prerequisites_built
        new_experiment_id = "TEST_p10_remediated"
        result = run_remediation(
            phase9_experiment_id,
            new_experiment_id,
            model_id="TEST_p10_remediated_model",
            repo_root=repo_root,
        )

        assert result["decision"]["decision"] in (
            "remediation_candidate",
            "remediation_rejected",
            "requires_new_external_validation",
        )
        assert len(result["comparison"]) == 5
        labels = [row["model"] for row in result["comparison"]]
        assert labels == [
            "original logistic (v1)",
            "VIF-reduced",
            "Stability-reduced (mechanical)",
            "Final remediated (gate D)",
            "HistGBM (challenger)",
        ]

        final_row = next(
            r for r in result["comparison"] if r["model"] == "Final remediated (gate D)"
        )
        # This is the real gate D finding on the real 30,000-row benchmark:
        # the documented policy resolves the original max VIF (56.83) and
        # ALSO the utilization_ratio/limit_exposure_distance collinearity
        # that only becomes visible once the bill/payment-amount pairs are
        # removed (see remediation_policy.yml) - both comparison
        # baselines (VIF-reduced's own elimination log, and the
        # mechanical stability-reduced row) independently corroborate
        # this, so the final remediated max VIF must land well below the
        # action threshold.
        assert final_row["max_vif"] is not None
        assert final_row["max_vif"] < 10.0
        assert final_row["n_features"] == 11

        report_path = repo_root / "reports/model_validation/remediation_report.md"
        assert report_path.is_file()
        assert "remediation_report.pt-BR.md" in {
            p.name for p in (repo_root / "reports/model_validation").glob("remediation_report*")
        }

        if result["decision"]["decision"] == "remediation_candidate":
            manifest_path = (
                repo_root / "reports/modeling/models/TEST_p10_remediated_model.manifest.json"
            )
            assert manifest_path.is_file()

        # v1 must never be touched by any of this.
        original_experiment = load_experiment(
            repo_root / "reports/modeling/experiments" / f"{phase9_experiment_id}.json"
        )
        assert len(original_experiment.feature_set) == 18


@pytest.mark.slow
class TestCliRemediate:
    def test_cli_remediate_and_compare(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Runs against the REAL repo (same convention as
        tests/test_cli_model_validation_monitor.py), using throwaway ids
        so the official EXP_behavioral_default_v2_reduced/
        MODEL_behavioral_default_v2_reduced artifacts are never touched.
        Cleaned up afterward."""
        import shutil

        from credlens.cli import main

        new_experiment_id = "TEST_cli10_remediated"
        new_model_id = "TEST_cli10_remediated_model"
        try:
            exit_code = main(
                [
                    "model",
                    "remediate",
                    "--model-id",
                    "MODEL_behavioral_default_v1",
                    "--new-experiment-id",
                    new_experiment_id,
                    "--new-model-id",
                    new_model_id,
                    "--json",
                ]
            )
            captured = capsys.readouterr()
            assert exit_code in (0, 1)
            payload = captured.out
            assert "decision" in payload

            exit_code = main(
                ["model", "compare-remediation", "--new-experiment-id", new_experiment_id]
            )
            captured = capsys.readouterr()
            assert exit_code == 0
            assert "Final remediated" in captured.out
        finally:
            for path in Path("reports/modeling/experiments").glob(f"{new_experiment_id}*"):
                if path.is_file():
                    path.unlink()
                else:
                    shutil.rmtree(path, ignore_errors=True)
            for path in Path("reports/modeling/models").glob(f"{new_model_id}*"):
                path.unlink(missing_ok=True)
            for path in Path("reports/model_validation/tables").glob(f"{new_experiment_id}*"):
                path.unlink(missing_ok=True)
            for path in Path("reports/modeling/tables").glob(f"{new_experiment_id}*"):
                path.unlink(missing_ok=True)
            lifecycle_path = Path("reports/model_validation/lifecycle") / f"{new_model_id}.json"
            lifecycle_path.unlink(missing_ok=True)
