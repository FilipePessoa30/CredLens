"""Tests for credlens.dashboard.charts (Phase 7 sections 11, 13): every
chart function must degrade to an empty (but valid) figure for an empty
DataFrame rather than raising, and must render real traces for real data."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from credlens.dashboard import charts


class TestEmptyDataframesNeverRaise:
    def test_line_by_scenario_empty(self) -> None:
        fig = charts.line_by_scenario(pd.DataFrame(), "x", "y", title="t", y_label="y")
        assert isinstance(fig, go.Figure)

    def test_bar_by_scenario_empty(self) -> None:
        fig = charts.bar_by_scenario(pd.DataFrame(), "x", "y", title="t", y_label="y")
        assert isinstance(fig, go.Figure)

    def test_funnel_by_scenario_empty(self) -> None:
        fig = charts.funnel_by_scenario(pd.DataFrame())
        assert isinstance(fig, go.Figure)

    def test_roll_rate_heatmap_empty(self) -> None:
        fig = charts.roll_rate_heatmap(pd.DataFrame())
        assert isinstance(fig, go.Figure)

    def test_vintage_curves_empty(self) -> None:
        fig = charts.vintage_curves(pd.DataFrame())
        assert isinstance(fig, go.Figure)

    def test_public_benchmark_bar_empty(self) -> None:
        fig = charts.public_benchmark_bar([])
        assert isinstance(fig, go.Figure)

    def test_missing_scenario_column_does_not_raise(self) -> None:
        df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
        fig = charts.line_by_scenario(df, "x", "y", title="t", y_label="y")
        assert isinstance(fig, go.Figure)


class TestRealDataProducesTraces:
    def test_line_by_scenario_with_real_data(self) -> None:
        df = pd.DataFrame(
            {
                "scenario": ["baseline", "baseline", "policy_expansion"],
                "snapshot_date": ["2024-01-31", "2024-02-29", "2024-01-31"],
                "outstanding_balance": [100.0, 110.0, 90.0],
            }
        )
        fig = charts.line_by_scenario(
            df, "snapshot_date", "outstanding_balance", title="t", y_label="y"
        )
        assert len(fig.data) == 2  # one trace per scenario

    def test_bar_by_scenario_with_real_data(self) -> None:
        df = pd.DataFrame({"scenario": ["baseline"], "x": ["Q1"], "y": [0.5]})
        fig = charts.bar_by_scenario(df, "x", "y", title="t", y_label="y", y_is_percent=True)
        assert len(fig.data) == 1

    def test_funnel_by_scenario_with_real_data(self) -> None:
        df = pd.DataFrame(
            {
                "scenario": ["baseline"],
                "applications_submitted": [100],
                "decisioned_applications": [95],
                "approved_count": [60],
                "booked_count": [50],
            }
        )
        fig = charts.funnel_by_scenario(df)
        assert len(fig.data) == 1

    def test_roll_rate_heatmap_with_real_data(self) -> None:
        df = pd.DataFrame(
            {
                "from_bucket": ["current", "current"],
                "to_bucket": ["current", "1-29"],
                "contract_count": [90, 10],
            }
        )
        fig = charts.roll_rate_heatmap(df)
        assert len(fig.data) == 1

    def test_vintage_curves_with_real_data(self) -> None:
        df = pd.DataFrame(
            {
                "scenario": ["baseline", "baseline"],
                "vintage_month": ["2024-01", "2024-01"],
                "months_on_book": [0, 1],
                "contracts_observed": [100, 100],
                "contracts_90plus": [0, 2],
            }
        )
        fig = charts.vintage_curves(df, "baseline")
        assert len(fig.data) == 1

    def test_grouped_bar(self) -> None:
        fig = charts.grouped_bar(["a", "b"], {"series1": [1, 2]}, title="t", y_label="y")
        assert len(fig.data) == 1

    def test_public_benchmark_bar_with_real_data(self) -> None:
        fig = charts.public_benchmark_bar([{"source_id": "uci-default-credit", "num_rows": 30000}])
        assert len(fig.data) == 1

    def test_charts_save_to_png_via_kaleido(self, tmp_path: Path) -> None:
        # Confirms these figures are actually renderable end to end - the
        # same path credlens.dashboard.exports.figure_to_png_bytes uses.
        df = pd.DataFrame({"scenario": ["baseline"], "x": ["Q1"], "y": [0.5]})
        fig = charts.bar_by_scenario(df, "x", "y", title="t", y_label="y")
        out = tmp_path / "chart.png"
        fig.write_image(str(out))
        assert out.stat().st_size > 0
