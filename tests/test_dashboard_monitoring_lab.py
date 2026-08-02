"""Tests for the Model Monitoring Lab dashboard page (Phase 9 section
22) - both the empty-state path (no monitoring run on disk) and, via
`AppTest`, a real render against whatever official monitoring run
already exists on disk. Same `streamlit.testing.v1.AppTest` harness
Phase 7/8's pages use - no mocked Streamlit internals."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from credlens.dashboard import monitoring_lab

_PAGE_PATH = "dashboard/pages/10_Model_Monitoring_Lab.py"


def _official_runs_exist() -> bool:
    runs_dir = Path("reports/monitoring/runs")
    return runs_dir.is_dir() and any(runs_dir.glob("*/run.json"))


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    monitoring_lab._list_run_ids.clear()
    monitoring_lab._load_run.clear()
    monitoring_lab._load_alerts.clear()
    monitoring_lab._load_decision.clear()
    monitoring_lab._load_pareto.clear()
    yield
    monitoring_lab._list_run_ids.clear()
    monitoring_lab._load_run.clear()
    monitoring_lab._load_alerts.clear()
    monitoring_lab._load_decision.clear()
    monitoring_lab._load_pareto.clear()


class TestEmptyStateWhenNoRunExists:
    def test_render_shows_empty_state_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(monitoring_lab, "_RUNS_DIR", tmp_path / "no_such_dir")
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=30)
        assert not at.exception
        assert any("No monitoring run" in info.value for info in at.info)


class TestCacheHelperEmptyBranches:
    """Phase 10B section 4.3 - direct unit tests for the `@st.cache_data`
    helpers' missing-artifact branches, faster than driving a full
    `AppTest` render for each one."""

    def test_load_run_returns_none_when_run_json_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(monitoring_lab, "_RUNS_DIR", tmp_path)
        assert monitoring_lab._load_run("RUN_never_existed") is None

    def test_load_alerts_returns_empty_list_when_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(monitoring_lab, "_ALERTS_DIR", tmp_path)
        assert monitoring_lab._load_alerts("RUN_never_existed") == []

    def test_load_decision_returns_none_when_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(monitoring_lab, "_VALIDATION_DIR", tmp_path)
        assert monitoring_lab._load_decision() is None

    def test_load_pareto_returns_empty_dataframe_when_dir_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(monitoring_lab, "_VALIDATION_TABLES_DIR", tmp_path / "no_such_dir")
        assert monitoring_lab._load_pareto().empty

    def test_load_pareto_returns_empty_dataframe_when_no_matches(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(monitoring_lab, "_VALIDATION_TABLES_DIR", tmp_path)
        assert monitoring_lab._load_pareto().empty

    @pytest.mark.skipif(
        not _official_runs_exist(), reason="Requires an official Phase 9 monitoring run."
    )
    def test_render_shows_empty_state_when_run_json_disappears_after_listing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A run listed by `_list_run_ids` but whose `run.json` can no
        longer be loaded (deleted between listing and loading, or
        corrupted) - `render_monitoring_lab`'s own `run_record is None`
        guard, distinct from "no runs exist at all"."""
        monkeypatch.setattr(monitoring_lab, "_load_run", lambda run_id: None)
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=30)
        assert not at.exception
        assert any("could not be loaded" in info.value for info in at.info)


@pytest.mark.skipif(
    not _official_runs_exist(), reason="Requires an official Phase 9 monitoring run."
)
class TestRealRunRendersWithoutError:
    def test_page_runs_with_no_exception(self) -> None:
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=60)
        assert not at.exception

    def test_every_tab_is_present(self) -> None:
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=60)
        assert len(at.tabs) == 8

    def test_metrics_show_batch_and_alert_counts(self) -> None:
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=60)
        metric_labels = {m.label for m in at.metric}
        assert "Batches" in metric_labels
        assert "Alerts" in metric_labels

    def test_simulation_warning_is_always_shown(self) -> None:
        at = AppTest.from_file(_PAGE_PATH)
        at.run(timeout=60)
        assert any("not a real production monitoring system" in w.value for w in at.warning)
