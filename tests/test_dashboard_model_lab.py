"""Tests for the Model Lab dashboard page (Phase 8 section 27) - both
the empty-state path (no experiment on disk) and, via `AppTest`, a real
render against the official `EXP_behavioral_default_v1` experiment
already on disk. No mocked Streamlit internals - this is the same
`streamlit.testing.v1.AppTest` harness Phase 7's 8 pages use."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from credlens.dashboard import model_lab

_PAGE_PATH = "dashboard/pages/9_Model_Lab.py"


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    model_lab._list_experiment_ids.clear()
    model_lab._load_experiment.clear()
    model_lab._load_table.clear()
    model_lab._load_json_table.clear()
    model_lab._default_experiment_index.clear()
    yield
    model_lab._list_experiment_ids.clear()
    model_lab._load_experiment.clear()
    model_lab._load_table.clear()
    model_lab._load_json_table.clear()
    model_lab._default_experiment_index.clear()


class TestDefaultExperimentIndex:
    def test_prefers_the_registered_candidate_over_the_last_alphabetically(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Mirrors the real Phase 10 gate D regression: sibling comparison
        # experiments sort AFTER the officially registered one.
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "MODEL_x.manifest.json").write_text(
            json.dumps({"status": "candidate", "experiment_id": "EXP_a"}), encoding="utf-8"
        )
        monkeypatch.setattr(model_lab, "_MODELING_ROOT", tmp_path)
        experiment_ids = ("EXP_a", "EXP_b_reduced", "EXP_b_reduced_vif_only")
        assert model_lab._default_experiment_index(experiment_ids) == 0

    def test_falls_back_to_the_last_experiment_when_no_candidate_is_registered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(model_lab, "_MODELING_ROOT", tmp_path)
        experiment_ids = ("EXP_a", "EXP_b")
        assert model_lab._default_experiment_index(experiment_ids) == 1

    def test_falls_back_when_models_dir_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(model_lab, "_MODELING_ROOT", tmp_path / "no_such_dir")
        assert model_lab._default_experiment_index(("EXP_a", "EXP_b")) == 1

    def test_corrupt_manifest_is_skipped_not_crashed_on(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "MODEL_broken.manifest.json").write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(model_lab, "_MODELING_ROOT", tmp_path)
        assert model_lab._default_experiment_index(("EXP_a", "EXP_b")) == 1


class TestCacheHelperEmptyBranches:
    def test_load_experiment_returns_none_when_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(model_lab, "_EXPERIMENTS_DIR", tmp_path)
        assert model_lab._load_experiment("EXP_never_existed") is None

    def test_load_table_returns_empty_dataframe_when_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(model_lab, "_TABLES_DIR", tmp_path)
        assert model_lab._load_table("EXP_never_existed", "predictions_test").empty

    def test_load_json_table_returns_none_when_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(model_lab, "_TABLES_DIR", tmp_path)
        assert model_lab._load_json_table("EXP_never_existed", "local_explanations") is None


class TestEmptyStateWhenNoExperimentExists:
    def test_render_model_lab_shows_empty_state_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(model_lab, "_EXPERIMENTS_DIR", tmp_path / "no_such_dir")
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=30)
        assert not at.exception
        assert any("No modeling experiment" in info.value for info in at.info)

    def test_shows_empty_state_when_experiment_not_yet_evaluated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(model_lab, "_list_experiment_ids", lambda: ["EXP_untrained"])
        monkeypatch.setattr(
            model_lab, "_load_experiment", lambda experiment_id: {"status": "created"}
        )
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=30)
        assert not at.exception
        assert any("has not been evaluated yet" in info.value for info in at.info)

    def test_shows_empty_state_when_no_test_predictions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pandas as pd

        monkeypatch.setattr(model_lab, "_list_experiment_ids", lambda: ["EXP_no_predictions"])
        monkeypatch.setattr(
            model_lab, "_load_experiment", lambda experiment_id: {"status": "evaluated"}
        )
        monkeypatch.setattr(model_lab, "_load_table", lambda experiment_id, name: pd.DataFrame())
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=30)
        assert not at.exception
        assert any("No test predictions found" in info.value for info in at.info)


@pytest.mark.skipif(
    not Path("reports/modeling/experiments/EXP_behavioral_default_v1.json").is_file(),
    reason="Requires the official Phase 8 experiment to have been run.",
)
class TestRealExperimentRendersWithoutError:
    def test_defaults_to_the_registered_candidate_not_a_gate_d_sibling(self) -> None:
        # Real-repo regression check: EXP_behavioral_default_v2_reduced
        # and its _vif_only/_stability_only siblings (Phase 10 gate D)
        # sort after v1 alphabetically and have no Phase 8 evaluation
        # tables - the page must still default to v1 (the registered
        # `candidate`), never silently show an all-zero overview.
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=60)
        experiment_select = next(sb for sb in at.selectbox if sb.label == "Experiment")
        assert experiment_select.value == "EXP_behavioral_default_v1"

    def test_page_runs_with_no_exception(self) -> None:
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=60)
        assert not at.exception

    def test_every_tab_is_present(self) -> None:
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=60)
        assert len(at.tabs) == 9

    def test_overview_metrics_show_real_numbers(self) -> None:
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=60)
        labels = {m.label for m in at.metric}
        assert "Prevalence (test)" in labels
        assert "ROC-AUC (test)" in labels

    def test_capacity_simulator_operating_point_selectbox(self) -> None:
        # Explicitly selects the fully Phase-8-evaluated official
        # experiment - Phase 10 gate D added sibling comparison
        # experiments (EXP_behavioral_default_v2_reduced and its
        # _vif_only/_stability_only baselines) that sort AFTER v1
        # alphabetically and have no thresholds table (they were never
        # run through 'credlens model evaluate'), so the page's default
        # ("last experiment_id") selection can no longer be assumed to be
        # a fully-evaluated one.
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=60)
        experiment_select = next(sb for sb in at.selectbox if sb.label == "Experiment")
        experiment_select.select("EXP_behavioral_default_v1").run(timeout=60)
        operating_point_select = next(sb for sb in at.selectbox if sb.label == "Operating point")
        operating_point_select.select("top_20_pct").run(timeout=60)
        assert not at.exception

    def test_switching_experiment_selector_does_not_crash(self) -> None:
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=60)
        experiment_select = next(sb for sb in at.selectbox if sb.label == "Experiment")
        experiment_select.select(experiment_select.options[0]).run(timeout=60)
        assert not at.exception

    def test_no_sensitive_attribute_ever_shown_as_a_feature_name(self) -> None:
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=60)
        markdown_text = " ".join(m.value for m in at.markdown)
        # X2/X3/X4/X5 (SEX/EDUCATION/MARRIAGE/AGE) must never appear as
        # if they were engineered training features.
        for sensitive_column in ("X2", "X3", "X4", "X5"):
            assert f"feature: {sensitive_column}" not in markdown_text.lower()
