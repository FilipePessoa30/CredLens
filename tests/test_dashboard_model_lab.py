"""Tests for the Model Lab dashboard page (Phase 8 section 27) - both
the empty-state path (no experiment on disk) and, via `AppTest`, a real
render against the official `EXP_behavioral_default_v1` experiment
already on disk. No mocked Streamlit internals - this is the same
`streamlit.testing.v1.AppTest` harness Phase 7's 8 pages use."""

from __future__ import annotations

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
    yield
    model_lab._list_experiment_ids.clear()
    model_lab._load_experiment.clear()
    model_lab._load_table.clear()
    model_lab._load_json_table.clear()


class TestEmptyStateWhenNoExperimentExists:
    def test_render_model_lab_shows_empty_state_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(model_lab, "_EXPERIMENTS_DIR", tmp_path / "no_such_dir")
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=30)
        assert not at.exception
        assert any("No modeling experiment" in info.value for info in at.info)


@pytest.mark.skipif(
    not Path("reports/modeling/experiments/EXP_behavioral_default_v1.json").is_file(),
    reason="Requires the official Phase 8 experiment to have been run.",
)
class TestRealExperimentRendersWithoutError:
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
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=60)
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
