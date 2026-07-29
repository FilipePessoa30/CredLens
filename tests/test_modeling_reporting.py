"""Tests for credlens.modeling.reporting (Phase 8 the staged CLI
pipeline): train -> evaluate -> compare -> explain -> audit-groups ->
stress-test -> register -> report, each stage persisting exactly what
the next stage needs, on an ISOLATED copy of the repo's config/data so no
test ever touches the real official experiment on disk.

Marked `slow` - this is the one place the real 30,000-row UCI benchmark,
tuning, calibration, bootstrap, split-stability, and robustness all run
together, in sequence, as the actual CLI does.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from credlens.modeling import reporting
from credlens.modeling.registry import Experiment, load_experiment

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def isolated_repo_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A minimal copy of just what credlens.modeling.reporting needs from
    disk (config/modeling/*.yml, the manifest, and the acquired UCI CSV) -
    shared read-only across every test in this module via unique
    experiment_ids, so the ~2.9MB source file is copied only once."""
    real_root = Path.cwd()
    root = tmp_path_factory.mktemp("isolated_repo")

    config_dir = root / "config" / "modeling"
    config_dir.mkdir(parents=True)
    for name in ("behavioral_default.yml", "feature_registry.yml", "evaluation.yml"):
        shutil.copy(real_root / "config" / "modeling" / name, config_dir / name)

    metadata_dir = root / "data" / "metadata"
    metadata_dir.mkdir(parents=True)
    shutil.copy(
        real_root / "data" / "metadata" / "file_manifest.csv", metadata_dir / "file_manifest.csv"
    )

    raw_dir = root / "data" / "raw" / "uci_default_credit"
    raw_dir.mkdir(parents=True)
    shutil.copy(
        real_root / "data" / "raw" / "uci_default_credit" / "default_of_credit_card_clients.csv",
        raw_dir / "default_of_credit_card_clients.csv",
    )
    return root


@pytest.fixture(scope="module")
def trained_experiment_id(isolated_repo_root: Path) -> str:
    experiment_id = "TEST_full_pipeline"
    reporting.train_experiment(experiment_id, repo_root=isolated_repo_root, seed=42)
    return experiment_id


@pytest.fixture(scope="module")
def evaluated_experiment_id(isolated_repo_root: Path, trained_experiment_id: str) -> str:
    reporting.evaluate_experiment(trained_experiment_id, repo_root=isolated_repo_root)
    return trained_experiment_id


class TestDataAuditAndValidateFeatures:
    def test_data_audit_report_matches_documented_numbers(self, isolated_repo_root: Path) -> None:
        report = reporting.data_audit_report(isolated_repo_root)
        assert report["num_rows"] == 30000
        assert report["target_positive_count"] == 6636

    def test_validate_features_report_is_clean(self, isolated_repo_root: Path) -> None:
        report = reporting.validate_features_report(isolated_repo_root)
        assert report["feature_count"] == 18
        assert report["all_finite"] is True


class TestCreateOfficialSplit:
    def test_creates_a_lockable_split(self, isolated_repo_root: Path) -> None:
        assignment = reporting.create_official_split(
            "TEST_split_only", repo_root=isolated_repo_root, seed=7
        )
        assert assignment.manifest.n_total == 30000
        split_path = (
            isolated_repo_root / "reports/modeling/experiments/TEST_split_only/split_assignment.csv"
        )
        assert split_path.is_file()

    def test_recreating_an_existing_split_is_refused(self, isolated_repo_root: Path) -> None:
        reporting.create_official_split("TEST_split_twice", repo_root=isolated_repo_root, seed=7)
        with pytest.raises(reporting.ReportingError, match="already exists"):
            reporting.create_official_split(
                "TEST_split_twice", repo_root=isolated_repo_root, seed=8
            )


class TestTrainExperiment:
    def test_trains_all_four_models_with_no_leakage_warnings(
        self, isolated_repo_root: Path, trained_experiment_id: str
    ) -> None:
        experiment = load_experiment(
            isolated_repo_root / "reports/modeling/experiments" / f"{trained_experiment_id}.json"
        )
        assert experiment.status == "trained"
        assert experiment.warnings == []
        models_dir = (
            isolated_repo_root / "reports/modeling/experiments" / trained_experiment_id / "models"
        )
        for kind in reporting.ALL_MODEL_KINDS:
            assert (models_dir / f"{kind}.joblib").is_file()

    def test_reuses_an_existing_split_rather_than_recreating_it(
        self, isolated_repo_root: Path, trained_experiment_id: str
    ) -> None:
        split_path = (
            isolated_repo_root
            / "reports/modeling/experiments"
            / trained_experiment_id
            / "split_assignment.csv"
        )
        original_hash = split_path.read_text(encoding="utf-8")
        reporting.train_experiment(trained_experiment_id, repo_root=isolated_repo_root, seed=999)
        assert split_path.read_text(encoding="utf-8") == original_hash


class TestEvaluateExperiment:
    def test_computes_metrics_for_every_model_kind(
        self, isolated_repo_root: Path, evaluated_experiment_id: str
    ) -> None:
        experiment = load_experiment(
            isolated_repo_root / "reports/modeling/experiments" / f"{evaluated_experiment_id}.json"
        )
        assert experiment.status == "evaluated"
        assert set(experiment.metrics["test"].keys()) == set(reporting.ALL_MODEL_KINDS)
        assert "bootstrap" in experiment.metrics
        assert "split_stability" in experiment.metrics
        assert "operating_points" in experiment.metrics

    def test_logistic_beats_dummy_on_the_real_benchmark(
        self, isolated_repo_root: Path, evaluated_experiment_id: str
    ) -> None:
        experiment = load_experiment(
            isolated_repo_root / "reports/modeling/experiments" / f"{evaluated_experiment_id}.json"
        )
        logit_pr_auc = experiment.metrics["test"]["logistic_regression"]["discrimination"]["pr_auc"]
        dummy_pr_auc = experiment.metrics["test"]["dummy_prior"]["discrimination"]["pr_auc"]
        assert logit_pr_auc > dummy_pr_auc


class TestCompareModels:
    def test_returns_one_row_per_model_kind(
        self, isolated_repo_root: Path, evaluated_experiment_id: str
    ) -> None:
        table = reporting.compare_models(evaluated_experiment_id, repo_root=isolated_repo_root)
        assert set(table["model"]) == set(reporting.ALL_MODEL_KINDS)
        assert "interpretability" in table.columns


class TestExplainExperiment:
    def test_writes_coefficients_permutation_and_local_explanations(
        self, isolated_repo_root: Path, evaluated_experiment_id: str
    ) -> None:
        import json

        import pandas as pd

        reporting.explain_experiment(evaluated_experiment_id, repo_root=isolated_repo_root)
        tables_dir = isolated_repo_root / "reports/modeling/tables"
        coefficients = pd.read_csv(tables_dir / f"{evaluated_experiment_id}__coefficients.csv")
        assert len(coefficients) == 18
        local = json.loads(
            (tables_dir / f"{evaluated_experiment_id}__local_explanations.json").read_text(
                encoding="utf-8"
            )
        )
        assert len(local) >= 5
        for case in local:
            reason_features = {r["feature"] for r in case["reason_codes"]}
            assert reason_features.isdisjoint({"X2", "X3", "X4", "X5"})


class TestAuditGroupsExperiment:
    def test_excludes_small_groups_from_ranking(
        self, isolated_repo_root: Path, evaluated_experiment_id: str
    ) -> None:
        reporting.explain_experiment(evaluated_experiment_id, repo_root=isolated_repo_root)
        experiment = reporting.audit_groups_experiment(
            evaluated_experiment_id, repo_root=isolated_repo_root
        )
        summary = experiment.subgroup_audit_summary
        assert "excluded_insufficient_groups" in summary
        assert summary["threshold"] > 0


class TestStressTestExperiment:
    def test_every_perturbation_ran_without_error(
        self, isolated_repo_root: Path, evaluated_experiment_id: str
    ) -> None:
        experiment = reporting.stress_test_experiment(
            evaluated_experiment_id, repo_root=isolated_repo_root
        )
        perturbations = experiment.robustness_summary["perturbations"]
        assert len(perturbations) == 9
        assert all(not p["had_error_or_nan"] for p in perturbations)


class TestRegisterExperimentModel:
    def test_registers_a_candidate_when_gates_pass(
        self, isolated_repo_root: Path, evaluated_experiment_id: str
    ) -> None:
        reporting.explain_experiment(evaluated_experiment_id, repo_root=isolated_repo_root)
        reporting.audit_groups_experiment(evaluated_experiment_id, repo_root=isolated_repo_root)
        reporting.stress_test_experiment(evaluated_experiment_id, repo_root=isolated_repo_root)
        gate_report, manifest = reporting.register_experiment_model(
            evaluated_experiment_id, "TEST_model_candidate", repo_root=isolated_repo_root
        )
        assert gate_report.eligible is True
        assert manifest is not None
        assert manifest.status == "candidate"

    def test_refuses_to_register_before_evaluation(self, isolated_repo_root: Path) -> None:
        reporting.train_experiment("TEST_not_evaluated_yet", repo_root=isolated_repo_root, seed=1)
        with pytest.raises(reporting.ReportingError, match="not been evaluated"):
            reporting.register_experiment_model(
                "TEST_not_evaluated_yet", "TEST_model_never", repo_root=isolated_repo_root
            )


class TestGenerateReportsAndFigures:
    def test_write_reports_produces_bilingual_cards_and_a_reproducible_fingerprint(
        self, isolated_repo_root: Path, evaluated_experiment_id: str
    ) -> None:
        reporting.explain_experiment(evaluated_experiment_id, repo_root=isolated_repo_root)
        written = reporting.write_reports(
            evaluated_experiment_id, None, repo_root=isolated_repo_root
        )
        assert set(written.keys()) == {
            "model_card.md",
            "model_card.pt-BR.md",
            "technical_report.md",
            "technical_report.pt-BR.md",
            "manifest.json",
        }
        for name in ("model_card.md", "model_card.pt-BR.md"):
            content = written[name].read_text(encoding="utf-8")
            assert (
                "Not suitable for real lending decisions" in content or "Não é adequado" in content
            )
        # Phase 10 gate C - model cards must disclose holdout reuse, not
        # claim an "untouched"/"opened only once" test set.
        assert (
            "Frozen evaluation holdout reused across documented validation phases"
            in written["model_card.md"].read_text(encoding="utf-8")
        )
        assert (
            "Holdout de avaliação congelado, reutilizado em fases documentadas de validação"
            in written["model_card.pt-BR.md"].read_text(encoding="utf-8")
        )

    def test_manifest_fingerprint_excludes_the_timestamp(
        self, isolated_repo_root: Path, evaluated_experiment_id: str
    ) -> None:
        import json
        import time

        first = reporting.write_reports(evaluated_experiment_id, None, repo_root=isolated_repo_root)
        first_manifest = json.loads(first["manifest.json"].read_text(encoding="utf-8"))
        time.sleep(0.01)
        second = reporting.write_reports(
            evaluated_experiment_id, None, repo_root=isolated_repo_root
        )
        second_manifest = json.loads(second["manifest.json"].read_text(encoding="utf-8"))
        assert first_manifest["content_fingerprint"] == second_manifest["content_fingerprint"]
        assert first_manifest["generated_at_utc"] != second_manifest["generated_at_utc"]

    def test_generate_figures_produces_sixteen_png_files(
        self, isolated_repo_root: Path, evaluated_experiment_id: str
    ) -> None:
        reporting.explain_experiment(evaluated_experiment_id, repo_root=isolated_repo_root)
        reporting.audit_groups_experiment(evaluated_experiment_id, repo_root=isolated_repo_root)
        reporting.stress_test_experiment(evaluated_experiment_id, repo_root=isolated_repo_root)
        paths = reporting.generate_figures(evaluated_experiment_id, repo_root=isolated_repo_root)
        assert len(paths) == 16
        for path in paths:
            assert path.is_file()
            assert path.stat().st_size > 0


def test_experiment_dataclass_to_dict_round_trips(
    isolated_repo_root: Path, trained_experiment_id: str
) -> None:
    experiment = load_experiment(
        isolated_repo_root / "reports/modeling/experiments" / f"{trained_experiment_id}.json"
    )
    assert isinstance(experiment, Experiment)
    assert experiment.to_dict()["experiment_id"] == trained_experiment_id
