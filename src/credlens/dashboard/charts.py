"""Interactive Plotly charts for the dashboard (Phase 7 sections 11, 13).

Every function here takes an already-queried DataFrame (never runs SQL
itself) and returns a `plotly.graph_objects.Figure`. No 3D, no decorative
gradients/animation, consistent scenario colours
(`credlens.dashboard.components.SCENARIO_COLORS`), axis units always
labeled.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go

from credlens.dashboard.components import BENCHMARK_COLOR, SCENARIO_COLORS

_LAYOUT_DEFAULTS: dict[str, Any] = {
    "template": "plotly_white",
    "margin": {"l": 40, "r": 20, "t": 50, "b": 40},
    "hovermode": "x unified",
    "legend": {"orientation": "h", "y": -0.2},
}


def _color_for(scenario: str) -> str:
    return SCENARIO_COLORS.get(scenario, "#888888")


def line_by_scenario(
    df: pd.DataFrame, x: str, y: str, *, title: str, y_label: str, y_is_percent: bool = False
) -> go.Figure:
    fig = go.Figure()
    if df.empty or "scenario" not in df.columns:
        fig.update_layout(title=title, **_LAYOUT_DEFAULTS)
        return fig
    for scenario, group in df.groupby("scenario"):
        g = group.sort_values(x)
        fig.add_trace(
            go.Scatter(
                x=g[x],
                y=g[y],
                mode="lines+markers",
                name=str(scenario),
                line={"color": _color_for(str(scenario))},
            )
        )
    fig.update_layout(
        title=title,
        yaxis_title=y_label,
        yaxis_tickformat=".1%" if y_is_percent else None,
        **_LAYOUT_DEFAULTS,
    )
    return fig


def bar_by_scenario(
    df: pd.DataFrame, x: str, y: str, *, title: str, y_label: str, y_is_percent: bool = False
) -> go.Figure:
    fig = go.Figure()
    if df.empty or "scenario" not in df.columns:
        fig.update_layout(title=title, **_LAYOUT_DEFAULTS)
        return fig
    for scenario, group in df.groupby("scenario"):
        fig.add_trace(
            go.Bar(
                x=group[x],
                y=group[y],
                name=str(scenario),
                marker_color=_color_for(str(scenario)),
            )
        )
    fig.update_layout(
        title=title,
        yaxis_title=y_label,
        yaxis_tickformat=".1%" if y_is_percent else None,
        barmode="group",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def funnel_by_scenario(df: pd.DataFrame, *, title: str = "Credit Funnel") -> go.Figure:
    stages = ["applications_submitted", "decisioned_applications", "approved_count", "booked_count"]
    stage_labels = ["Submitted", "Decisioned", "Approved", "Booked"]
    fig = go.Figure()
    if df.empty:
        fig.update_layout(title=title, **_LAYOUT_DEFAULTS)
        return fig
    agg = df.groupby("scenario")[stages].sum()
    for scenario, row in agg.iterrows():
        fig.add_trace(
            go.Funnel(
                name=str(scenario),
                y=stage_labels,
                x=[row[s] for s in stages],
                marker={"color": _color_for(str(scenario))},
            )
        )
    fig.update_layout(title=title, **_LAYOUT_DEFAULTS)
    return fig


def roll_rate_heatmap(df: pd.DataFrame, *, title: str = "Roll-Rate Matrix") -> go.Figure:
    bucket_order = ["current", "1-29", "30-59", "60-89", "90+"]
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title=title, **_LAYOUT_DEFAULTS)
        return fig
    pivot = (
        df.groupby(["from_bucket", "to_bucket"])["contract_count"]
        .sum()
        .unstack(fill_value=0)
        .reindex(index=bucket_order, columns=bucket_order, fill_value=0)
    )
    fig = go.Figure(
        data=go.Heatmap(
            z=pivot.to_numpy(),
            x=bucket_order,
            y=bucket_order,
            colorscale="Blues",
            text=pivot.to_numpy(),
            texttemplate="%{text}",
            hovertemplate="From %{y} to %{x}: %{z} contract-months<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="To bucket (this month)",
        yaxis_title="From bucket (prior month)",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def vintage_curves(
    df: pd.DataFrame, scenario: str = "baseline", *, title: str = "Vintage Curves"
) -> go.Figure:
    fig = go.Figure()
    g = df[df["scenario"] == scenario] if "scenario" in df.columns else df
    if g.empty:
        fig.update_layout(title=title, **_LAYOUT_DEFAULTS)
        return fig
    for vintage_month, cohort in g.groupby("vintage_month"):
        cohort = cohort.sort_values("months_on_book")
        cohort = cohort[cohort["contracts_observed"] > 0]
        rate = cohort["contracts_90plus"] / cohort["contracts_observed"].replace(0, pd.NA)
        fig.add_trace(
            go.Scatter(
                x=cohort["months_on_book"],
                y=rate,
                mode="lines+markers",
                name=str(vintage_month)[:7],
            )
        )
    fig.update_layout(
        title=title,
        xaxis_title="Months on book (MOB)",
        yaxis_title="90+ DPD incidence",
        yaxis_tickformat=".1%",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def grouped_bar(
    categories: list[str], series: dict[str, list[float]], *, title: str, y_label: str
) -> go.Figure:
    fig = go.Figure()
    for name, values in series.items():
        fig.add_trace(go.Bar(x=categories, y=values, name=name))
    fig.update_layout(title=title, yaxis_title=y_label, barmode="group", **_LAYOUT_DEFAULTS)
    return fig


def public_benchmark_bar(
    profiles: list[dict[str, Any]], *, title: str = "Public Sources"
) -> go.Figure:
    fig = go.Figure()
    if not profiles:
        fig.update_layout(title=title, **_LAYOUT_DEFAULTS)
        return fig
    fig.add_trace(
        go.Bar(
            x=[p["source_id"] for p in profiles],
            y=[p["num_rows"] for p in profiles],
            marker_color=BENCHMARK_COLOR,
        )
    )
    fig.update_layout(title=title, yaxis_title="Rows / observations", **_LAYOUT_DEFAULTS)
    return fig
