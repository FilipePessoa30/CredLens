"""Direct unit tests for the empty-state branch of every dashboard page
(Phase 7 section 12: "selecao vazia deve produzir estado vazio, nao
erro") - a real build/demo package always has data for every table, so
`streamlit.testing.v1.AppTest` alone never exercises these branches."""

from __future__ import annotations

import pytest

from credlens.dashboard import pages
from credlens.dashboard.data_access import DashboardData
from credlens.dashboard.filters import FilterState


def _empty_data(mode: str = "demo") -> DashboardData:
    return DashboardData(
        mode=mode,
        fingerprint="f" * 64,
        build_id="BUILD_empty_test",
        suite_id=None if mode == "demo" else "SUITE_empty_test",
        tables={},
        composition={},
        insights=[],
    )


class TestEmptyStateNeverRaises:
    def test_executive_overview(self) -> None:
        pages.render_executive_overview(_empty_data(), FilterState())

    def test_credit_funnel(self) -> None:
        pages.render_credit_funnel(_empty_data(), FilterState())

    def test_portfolio_delinquency(self) -> None:
        pages.render_portfolio_delinquency(_empty_data(), FilterState())

    def test_vintages_roll_rates(self) -> None:
        pages.render_vintages_roll_rates(_empty_data(), FilterState())

    def test_cure_collections_recovery(self) -> None:
        pages.render_cure_collections_recovery(_empty_data(), FilterState())

    def test_scenario_lab(self) -> None:
        pages.render_scenario_lab(_empty_data(), FilterState())

    def test_data_quality_methodology(self) -> None:
        pages.render_data_quality_methodology(_empty_data(mode="warehouse"))

    def test_public_benchmarks(self) -> None:
        pages.render_public_benchmarks()


class TestScenarioLabWithoutRobustnessReport:
    def test_no_robustness_report_shows_info_not_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("credlens.dashboard.pages.load_robustness_report", lambda: {})
        pages.render_scenario_lab(_empty_data(), FilterState())


class TestPublicBenchmarksWithoutSources:
    def test_no_public_sources_shows_info_not_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("credlens.analysis.benchmark.profile_public_sources", lambda: [])
        pages.render_public_benchmarks()
