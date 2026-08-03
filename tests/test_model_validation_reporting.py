"""Tests for credlens.model_validation.reporting - the full Phase 9
independent-validation/challenger/reduced-model orchestration, on the
real, isolated, full 30,000-row pipeline (`phase9_isolated_repo_root`).

Marked `slow`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from credlens.model_validation import reporting
from credlens.model_validation.reporting import ModelValidationError

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

    def test_auto_detects_the_single_registered_experiment_id(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        # `phase9_isolated_repo_root`'s registered candidate/challenger
        # models both belong to the SAME (only) experiment_id at this
        # point in the module, so omitting `experiment_id` must resolve
        # it unambiguously rather than raising.
        reporting.register_challenger_experiment(
            phase9_experiment_id, "TEST_p9_challenger", repo_root=phase9_isolated_repo_root
        )
        table = reporting.compare_candidates(repo_root=phase9_isolated_repo_root)
        assert len(table) == 2


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

    def test_returns_none_when_vif_elimination_drops_nothing(
        self,
        phase9_isolated_repo_root: Path,
        phase9_experiment_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Phase 9 section 7.3: only a real, justified feature drop
        creates a reduced experiment - a VIF audit that keeps every
        feature must return `None`, never an identical duplicate
        experiment."""
        from credlens.modeling.features import FEATURE_COLUMNS

        monkeypatch.setattr(
            reporting, "iteratively_reduce_by_vif", lambda x_train, threshold: (FEATURE_COLUMNS, [])
        )
        experiment = reporting.build_reduced_experiment(
            phase9_experiment_id, "TEST_p9_reduced_noop", repo_root=phase9_isolated_repo_root
        )
        assert experiment is None


class TestDocumentationComplete:
    """Fase 10C priority 2 - `_documentation_complete`'s 3 branches
    (missing files; missing EN disclosure; missing PT-BR disclosure) -
    the `phase9_isolated_repo_root` fixture never copies `reports/`, so
    the "missing" branch is exercised for free; the other two need a
    deliberately-wrong model_card written into it."""

    def test_missing_report_files_is_incomplete(self, tmp_path: Path) -> None:
        # A bare tmp_path, never `phase9_isolated_repo_root` - that shared
        # fixture's own setup already writes a real model_card.md/
        # technical_report.md via `credlens.modeling.reporting.write_
        # reports`, so it is never actually missing documentation.
        complete, detail = reporting._documentation_complete(tmp_path)
        assert complete is False
        assert "missing" in detail.lower()

    def test_missing_en_disclosure_sentence_is_incomplete(
        self, phase9_isolated_repo_root: Path
    ) -> None:
        modeling_dir = phase9_isolated_repo_root / "reports" / "modeling"
        modeling_dir.mkdir(parents=True, exist_ok=True)
        (modeling_dir / "model_card.md").write_text("no disclosure here", encoding="utf-8")
        (modeling_dir / "model_card.pt-BR.md").write_text(
            "Não é adequado para decisões reais", encoding="utf-8"
        )
        (modeling_dir / "technical_report.md").write_text("x", encoding="utf-8")
        complete, detail = reporting._documentation_complete(phase9_isolated_repo_root)
        assert complete is False
        assert "mandatory" in detail.lower()

    def test_missing_pt_br_disclosure_sentence_is_incomplete(
        self, phase9_isolated_repo_root: Path
    ) -> None:
        modeling_dir = phase9_isolated_repo_root / "reports" / "modeling"
        modeling_dir.mkdir(parents=True, exist_ok=True)
        (modeling_dir / "model_card.md").write_text(
            "Not suitable for real lending decisions.", encoding="utf-8"
        )
        (modeling_dir / "model_card.pt-BR.md").write_text(
            "sem a frase obrigatoria", encoding="utf-8"
        )
        (modeling_dir / "technical_report.md").write_text("x", encoding="utf-8")
        complete, detail = reporting._documentation_complete(phase9_isolated_repo_root)
        assert complete is False
        assert "pt-br" in detail.lower()

    def test_all_present_and_correct_is_complete(self, phase9_isolated_repo_root: Path) -> None:
        modeling_dir = phase9_isolated_repo_root / "reports" / "modeling"
        modeling_dir.mkdir(parents=True, exist_ok=True)
        (modeling_dir / "model_card.md").write_text(
            "Not suitable for real lending decisions.", encoding="utf-8"
        )
        (modeling_dir / "model_card.pt-BR.md").write_text(
            "Não é adequado para decisões reais de crédito.", encoding="utf-8"
        )
        (modeling_dir / "technical_report.md").write_text("x", encoding="utf-8")
        complete, _detail = reporting._documentation_complete(phase9_isolated_repo_root)
        assert complete is True


class TestRunInputContractSelfTest:
    """Fase 10C priority 2 - `_run_input_contract_self_test` is a
    meta-check that the input contract itself correctly rejects/
    quarantines 6 synthetic corruption probes; its own two failure
    branches (a probe that SHOULD raise but doesn't; a probe that
    SHOULD be quarantined but isn't) only fire if the contract itself
    regresses - simulated here via a stubbed `validate_input_contract`,
    never by weakening the real contract."""

    def test_passes_on_real_clean_data(self, tiny_uci_frame: pd.DataFrame) -> None:
        assert reporting._run_input_contract_self_test(tiny_uci_frame) is True

    def test_false_when_a_batch_level_probe_is_not_rejected(
        self, tiny_uci_frame: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _FakeCleanReport:
            n_quarantined_rows = 0

        monkeypatch.setattr(
            reporting, "validate_input_contract", lambda df, mode: _FakeCleanReport()
        )
        assert reporting._run_input_contract_self_test(tiny_uci_frame) is False

    def test_false_when_a_row_level_probe_is_not_quarantined(
        self, tiny_uci_frame: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from credlens.modeling.input_contract import Mode
        from credlens.modeling.input_contract import validate_input_contract as real_validate

        call_count = {"n": 0}

        def fake_validate(df: pd.DataFrame, mode: Mode) -> Any:
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return real_validate(df, mode)

            class _FakeCleanReport:
                n_quarantined_rows = 0

            return _FakeCleanReport()

        monkeypatch.setattr(reporting, "validate_input_contract", fake_validate)
        assert reporting._run_input_contract_self_test(tiny_uci_frame) is False


class TestCheckReproducibility:
    def test_matching_hash_is_reproducible(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str, validated: object
    ) -> None:
        from credlens.model_validation.evidence import load_evidence

        evidence = load_evidence(phase9_experiment_id, repo_root=phase9_isolated_repo_root)
        ok, detail = reporting._check_reproducibility(evidence, phase9_isolated_repo_root)
        assert ok is True
        assert "matches" in detail.lower()

    def test_changed_predictions_file_is_not_reproducible(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str, validated: object
    ) -> None:
        from credlens.model_validation.evidence import load_evidence

        evidence = load_evidence(phase9_experiment_id, repo_root=phase9_isolated_repo_root)
        predictions_path = (
            phase9_isolated_repo_root
            / "reports/modeling/tables"
            / f"{phase9_experiment_id}__predictions_test.csv"
        )
        original = predictions_path.read_text(encoding="utf-8")
        try:
            predictions_path.write_text(original + "\n# tampered\n", encoding="utf-8")
            ok, detail = reporting._check_reproducibility(evidence, phase9_isolated_repo_root)
            assert ok is False
            assert "changed" in detail.lower()
        finally:
            predictions_path.write_text(original, encoding="utf-8")


class TestIndependentValidationResultToDict:
    """Fase 10C priority 2 (continued) - `IndependentValidationResult.
    to_dict()` was never actually called by any existing test."""

    def test_to_dict_matches_the_real_result(
        self, validated: reporting.IndependentValidationResult
    ) -> None:
        as_dict = validated.to_dict()
        assert as_dict["experiment_id"] == validated.experiment_id
        assert as_dict["model_id"] == validated.model_id
        assert as_dict["decision"] == validated.decision.to_dict()
        assert as_dict["n_permutations_control1"] == validated.n_permutations_control1
        assert as_dict["n_permutations_control2"] == validated.n_permutations_control2


class TestValidateIndependentMissingModelArtifact:
    """Fase 10C priority 2 (continued) - a registered experiment whose
    trained model artifact is missing from disk (deleted/moved after
    training, before validation) - a real, if rare, operational state.
    The joblib file is renamed away and restored in `finally`, mirroring
    the tamper-and-restore pattern already used for reproducibility."""

    def test_missing_logistic_regression_artifact_raises(
        self,
        phase9_isolated_repo_root: Path,
        phase9_experiment_id: str,
        phase9_model_id: str,
    ) -> None:
        model_path = (
            phase9_isolated_repo_root
            / "reports/modeling/experiments"
            / phase9_experiment_id
            / "models"
            / "logistic_regression.joblib"
        )
        backup_path = model_path.with_name(model_path.name + ".bak")
        model_path.rename(backup_path)
        try:
            with pytest.raises(ModelValidationError, match="No trained logistic regression"):
                reporting.validate_independent(
                    phase9_model_id,
                    full_permutations=False,
                    repo_root=phase9_isolated_repo_root,
                )
        finally:
            backup_path.rename(model_path)


class TestRegisterChallengerMissingModelArtifact:
    def test_missing_hist_gradient_boosting_artifact_raises(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        model_path = (
            phase9_isolated_repo_root
            / "reports/modeling/experiments"
            / phase9_experiment_id
            / "models"
            / "hist_gradient_boosting.joblib"
        )
        backup_path = model_path.with_name(model_path.name + ".bak")
        model_path.rename(backup_path)
        try:
            with pytest.raises(ModelValidationError, match="No trained HistGradientBoosting"):
                reporting.register_challenger_experiment(
                    phase9_experiment_id,
                    "TEST_p9_challenger_missing_artifact",
                    repo_root=phase9_isolated_repo_root,
                )
        finally:
            backup_path.rename(model_path)


class TestFindManifestByStatus:
    def test_no_matching_manifest_raises(
        self, phase9_isolated_repo_root: Path, phase9_experiment_id: str
    ) -> None:
        with pytest.raises(ModelValidationError, match="No registered model"):
            reporting._find_manifest_by_status(
                "no_such_status_at_all", phase9_experiment_id, phase9_isolated_repo_root
            )


class TestCompareCandidatesAutoDetectAmbiguous:
    """Fase 10C priority 2 (continued) - `compare_candidates(experiment_id=
    None)`'s auto-detection must refuse to guess when the registered
    manifests span more than one experiment_id. A fresh `tmp_path` with
    two hand-written, minimal manifest stubs (real schema fields, no
    training involved) - never `phase9_isolated_repo_root`, which by this
    point in the module only ever has ONE experiment_id registered."""

    def test_multiple_experiment_ids_registered_raises(self, tmp_path: Path) -> None:
        models_dir = tmp_path / "reports" / "modeling" / "models"
        models_dir.mkdir(parents=True)
        for i, experiment_id in enumerate(["TEST_exp_a", "TEST_exp_b"]):
            manifest = {
                "model_id": f"TEST_model_{i}",
                "experiment_id": experiment_id,
                "status": "candidate",
            }
            (models_dir / f"TEST_model_{i}.manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
        with pytest.raises(ModelValidationError, match="Cannot auto-detect"):
            reporting.compare_candidates(repo_root=tmp_path)


class TestGenerateValidationFiguresMissingMatplotlib:
    """Fase 10C priority 2 (continued) - matplotlib is a real dependency
    of this project (not actually missing), so its absence is simulated
    the standard way (a `None` entry in `sys.modules` makes the next
    `import matplotlib` raise `ImportError`, exactly as it would in an
    environment genuinely missing the optional `analysis`/`modeling`
    extras) rather than by uninstalling it, which would break the rest
    of the suite."""

    def test_missing_matplotlib_raises_a_clear_error(
        self,
        phase9_isolated_repo_root: Path,
        phase9_experiment_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setitem(sys.modules, "matplotlib", None)
        with pytest.raises(ModelValidationError, match="matplotlib"):
            reporting.generate_validation_figures(
                phase9_experiment_id, repo_root=phase9_isolated_repo_root
            )
