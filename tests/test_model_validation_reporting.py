"""Tests for credlens.model_validation.reporting - the full Phase 9
independent-validation/challenger/reduced-model orchestration, on the
real, isolated, full 30,000-row pipeline (`phase9_isolated_repo_root`).

Marked `slow`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from credlens.model_validation import reporting

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def validated(
    phase9_isolated_repo_root: Path, phase9_model_id: str
) -> reporting.IndependentValidationResult:
    return reporting.validate_independent(
        phase9_model_id, full_permutations=False, repo_root=phase9_isolated_repo_root
    )


class TestValidateIndependent:
    def test_produces_a_decision(self, validated: reporting.IndependentValidationResult) -> None:
        assert validated.decision.decision in (
            "validation_passed",
            "validation_passed_with_limitations",
            "validation_failed",
        )
        assert len(validated.decision.gates) == 14

    def test_writes_evidence_and_tables(
        self,
        phase9_isolated_repo_root: Path,
        phase9_experiment_id: str,
        validated: reporting.IndependentValidationResult,
    ) -> None:
        evidence_path = (
            phase9_isolated_repo_root
            / "reports/model_validation/evidence"
            / f"{phase9_experiment_id}.json"
        )
        assert evidence_path.is_file()
        tables_dir = phase9_isolated_repo_root / "reports/model_validation/tables"
        assert (tables_dir / f"{phase9_experiment_id}__vif.csv").is_file()
        assert (tables_dir / f"{phase9_experiment_id}__coefficient_classification.csv").is_file()
        assert (tables_dir / f"{phase9_experiment_id}__subgroup_gaps.csv").is_file()

    def test_unregistered_model_raises(self, phase9_isolated_repo_root: Path) -> None:
        from credlens.modeling.registry import RegistryError

        with pytest.raises(RegistryError):
            reporting.validate_independent(
                "TEST_no_such_model", repo_root=phase9_isolated_repo_root
            )


class TestValidationReports:
    def test_writes_bilingual_reports(
        self,
        phase9_isolated_repo_root: Path,
        phase9_experiment_id: str,
        validated: reporting.IndependentValidationResult,
    ) -> None:
        written = reporting.write_validation_reports(
            phase9_experiment_id, repo_root=phase9_isolated_repo_root
        )
        assert set(written.keys()) == {"validation_report.md", "validation_report.pt-BR.md"}
        en_text = written["validation_report.md"].read_text(encoding="utf-8")
        pt_text = written["validation_report.pt-BR.md"].read_text(encoding="utf-8")
        assert "Not suitable for real lending decisions" in en_text
        assert "Não é adequado para decisões reais" in pt_text
        # Phase 10 gate C - the holdout must never be called "untouched"
        # or "opened only once"; both bilingual reports must carry the
        # explicit reuse disclosure instead (the disclosure text itself
        # quotes "untouched" only to disclaim it, so this checks for the
        # affirmative reuse statement, not a blanket absence of the word).
        assert "Frozen evaluation holdout reused across documented validation phases" in en_text
        assert (
            "Holdout de avaliação congelado, reutilizado em fases documentadas de validação"
            in pt_text
        )


class TestRegisterChallenger:
    def test_registers_a_challenger_never_candidate(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        manifest = reporting.register_challenger_experiment(
            phase9_experiment_id, "TEST_p9_challenger", repo_root=phase9_isolated_repo_root
        )
        assert manifest.status == "challenger"
        assert manifest.status != "candidate"
        assert manifest.status != "production"


class TestCompareCandidates:
    def test_produces_a_two_row_pareto_table(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        # Depends on TestRegisterChallenger having run in the same module
        # (pytest executes classes in file order); guard just in case.
        reporting.register_challenger_experiment(
            phase9_experiment_id, "TEST_p9_challenger", repo_root=phase9_isolated_repo_root
        )
        table = reporting.compare_candidates(
            phase9_experiment_id, repo_root=phase9_isolated_repo_root
        )
        assert len(table) == 2
        assert set(table["model"]) == {
            "logistic_regression (candidate)",
            "hist_gradient_boosting (challenger)",
        }
        assert (table["pr_auc"] > 0).all()


class TestBuildReducedExperiment:
    def test_reduces_features_when_vif_is_high(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        experiment = reporting.build_reduced_experiment(
            phase9_experiment_id, "TEST_p9_reduced", repo_root=phase9_isolated_repo_root
        )
        assert experiment is not None
        assert len(experiment.feature_set) < 18
        assert "months_delinquent_count" not in experiment.feature_set or (
            "consecutive_months_delinquent" not in experiment.feature_set
        )
        assert experiment.metrics["test"]["discrimination"]["roc_auc"] > 0.5
