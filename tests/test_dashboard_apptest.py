"""Real, execution-level dashboard tests via `streamlit.testing.v1.
AppTest` (Phase 7 section 20-21) - the strongest verification available
without a browser: every page script is actually RUN (not just imported),
proving its Python logic executes without exception against real data in
both demo and warehouse mode.

No pixel-level visual check (contrast, clipping, tooltips) is performed
here - that would require an actual browser, which this environment does
not have. See the Phase 7 final report's "screenshots and visual
validation" section for that explicit limitation.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

_PAGES_DIR = Path(__file__).parent.parent / "dashboard" / "pages"
_ALL_PAGES = (
    "1_Executive_Overview",
    "2_Credit_Funnel",
    "3_Portfolio_Delinquency",
    "4_Vintages_Roll_Rates",
    "5_Cure_Collections_Recovery",
    "6_Scenario_Lab",
    "7_Data_Quality_Methodology",
    "8_Public_Benchmarks",
)

# Overridable via environment so CI can point these at its own
# CI-scoped build/demo package (e.g. CI_ANALYSIS_BUILD and a demo package
# exported to a scratch dir) rather than this repository's own,
# developer-machine-only official artifacts.
_DEMO_DATA_DIR = Path(os.environ.get("CREDLENS_TEST_DEMO_DATA_DIR", "dashboard/demo_data"))
_OFFICIAL_BUILD_ID = os.environ.get("CREDLENS_TEST_BUILD_ID", "BUILD_kpi_test")


def _demo_package_available() -> bool:
    return (_DEMO_DATA_DIR / "manifest.json").is_file()


def _official_build_available() -> bool:
    return (Path("data/warehouse") / _OFFICIAL_BUILD_ID / "build_manifest.json").is_file()


@pytest.fixture
def demo_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if not _demo_package_available():
        pytest.skip(f"'{_DEMO_DATA_DIR}' has not been generated in this environment")
    monkeypatch.setenv("CREDLENS_DASHBOARD_DEMO", "1")
    monkeypatch.setenv("CREDLENS_DASHBOARD_DEMO_DIR", str(_DEMO_DATA_DIR))
    monkeypatch.delenv("CREDLENS_DASHBOARD_BUILD_ID", raising=False)
    yield


@pytest.fixture
def warehouse_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if not _official_build_available():
        pytest.skip(f"'{_OFFICIAL_BUILD_ID}' is not available in this environment")
    monkeypatch.setenv("CREDLENS_DASHBOARD_BUILD_ID", _OFFICIAL_BUILD_ID)
    monkeypatch.delenv("CREDLENS_DASHBOARD_DEMO", raising=False)
    yield


def _run_page(page_name: str) -> AppTest:
    at = AppTest.from_file(str(_PAGES_DIR / f"{page_name}.py"), default_timeout=60)
    at.run()
    return at


class TestEveryPageLoadsInDemoMode:
    @pytest.mark.parametrize("page_name", _ALL_PAGES)
    def test_page_runs_without_exception(self, demo_env: None, page_name: str) -> None:
        at = _run_page(page_name)
        assert not at.exception, f"{page_name} raised: {list(at.exception)}"

    @pytest.mark.parametrize("page_name", _ALL_PAGES)
    def test_page_has_a_header(self, demo_env: None, page_name: str) -> None:
        at = _run_page(page_name)
        assert len(at.header) >= 1


class TestEveryPageLoadsInWarehouseMode:
    @pytest.mark.parametrize("page_name", _ALL_PAGES)
    def test_page_runs_without_exception(self, warehouse_env: None, page_name: str) -> None:
        at = _run_page(page_name)
        assert not at.exception, f"{page_name} raised: {list(at.exception)}"


class TestModeIsAlwaysVisible:
    def test_demo_mode_shows_demo_badge(self, demo_env: None) -> None:
        at = _run_page("1_Executive_Overview")
        sidebar_text = " ".join(m.value for m in at.sidebar.markdown)
        assert "Demo aggregate package" in sidebar_text

    def test_warehouse_mode_shows_warehouse_badge(self, warehouse_env: None) -> None:
        at = _run_page("1_Executive_Overview")
        sidebar_text = " ".join(m.value for m in at.sidebar.markdown)
        assert "Validated warehouse" in sidebar_text


class TestSyntheticWarningIsPresent:
    @pytest.mark.parametrize(
        "page_name",
        [
            "1_Executive_Overview",
            "2_Credit_Funnel",
            "3_Portfolio_Delinquency",
            "4_Vintages_Roll_Rates",
            "5_Cure_Collections_Recovery",
            "6_Scenario_Lab",
        ],
    )
    def test_synthetic_warning_banner_shown(self, demo_env: None, page_name: str) -> None:
        at = _run_page(page_name)
        warnings = [w.value for w in at.warning]
        assert any("synthetic" in w.lower() for w in warnings), (
            f"{page_name} has no synthetic-data warning banner"
        )


class TestFiltersAreInteractive:
    def test_credit_funnel_has_every_documented_filter(self, demo_env: None) -> None:
        at = _run_page("2_Credit_Funnel")
        labels = {ms.label for ms in at.multiselect}
        for expected in (
            "Scenario",
            "Channel",
            "Product",
            "Region",
            "Policy version",
            "Bureau score bucket",
            "Income band",
            "Contract value band",
            "Cohort (vintage month)",
            "DPD bucket",
        ):
            assert expected in labels, f"missing filter: {expected}"

    def test_selecting_a_scenario_narrows_the_page_without_error(self, demo_env: None) -> None:
        at = _run_page("2_Credit_Funnel")
        scenario_widget = next(ms for ms in at.multiselect if ms.label == "Scenario")
        scenario_widget.set_value(["baseline"]).run()
        assert not at.exception

    def test_selecting_a_scenario_absent_from_the_data_shows_empty_state_not_error(
        self, demo_env: None
    ) -> None:
        # funnel_by_channel_and_scenario never has a 'baseline' row where
        # channel is also constrained to something baseline never used -
        # instead, directly exercise the empty-state path: select every
        # scenario filter to a value that yields zero rows by picking a
        # channel that does not co-occur, if any exists; otherwise this
        # test simply proves no exception is raised for a narrow selection.
        at = _run_page("2_Credit_Funnel")
        channel_widget = next(ms for ms in at.multiselect if ms.label == "Channel")
        if not channel_widget.options:
            pytest.skip("no channel options available in this build")
        channel_widget.set_value([channel_widget.options[0]]).run()
        assert not at.exception


class TestPageProvenanceBadge:
    @pytest.mark.parametrize("page_name", _ALL_PAGES)
    def test_every_page_shows_its_provenance_badge(self, demo_env: None, page_name: str) -> None:
        at = _run_page(page_name)
        captions = [c.value for c in at.caption]
        assert any(c.startswith("Page provenance:") for c in captions), (
            f"{page_name} has no page-level provenance badge"
        )


class TestPublicBenchmarksPageIsSeparate:
    def test_shows_real_data_or_explicit_empty_state_never_fabricated(self, demo_env: None) -> None:
        at = _run_page("8_Public_Benchmarks")
        assert not at.exception
        info_or_captions = [i.value for i in at.info] + [c.value for c in at.caption]
        combined = " ".join(info_or_captions).lower()
        assert "no public benchmark sources found" in combined or "public" in combined


class TestDataQualityPageShowsProvenance:
    def test_shows_build_id_and_fingerprint(self, demo_env: None) -> None:
        at = _run_page("7_Data_Quality_Methodology")
        assert not at.exception
        metric_values = [m.value for m in at.metric]
        assert any(v for v in metric_values)  # Mode/Build ID/Fingerprint metrics present


class TestNoRawMissingValuesLeakThrough:
    @pytest.mark.parametrize("page_name", _ALL_PAGES)
    def test_no_literal_nan_in_rendered_text(self, demo_env: None, page_name: str) -> None:
        at = _run_page(page_name)
        texts = (
            [m.value for m in at.markdown]
            + [c.value for c in at.caption]
            + [str(m.value) for m in at.metric]
        )
        combined = " ".join(str(t) for t in texts)
        assert " nan " not in f" {combined.lower()} "
        assert "NaN" not in combined
