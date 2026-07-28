"""Interactive Plotly charts for the Model Monitoring Lab page (Phase 9
section 22) - every function here takes already-computed values read
from `reports/monitoring/` (a run record, an alert list, a Pareto
comparison table) - it never rescoring a batch or recomputing drift
itself. Every function degrades to a valid, empty figure on empty input,
matching `credlens.dashboard.model_charts`'s convention.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go

_LAYOUT_DEFAULTS: dict[str, Any] = {
    "template": "plotly_white",
    "margin": {"l": 40, "r": 20, "t": 50, "b": 40},
    "hovermode": "closest",
    "legend": {"orientation": "h", "y": -0.2},
}

_SEVERITY_COLORS = {"high": "#8b1a1a", "medium": "#e6842e", "low": "#6b7280"}


def data_quality_status_chart(batches: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure()
    if not batches:
        fig.update_layout(title="Data quality by batch (no data)", **_LAYOUT_DEFAULTS)
        return fig
    sequences = [b["batch_sequence"] for b in batches]
    for metric, color in (
        ("missingness_rate", "#1f5fa8"),
        ("domain_violation_rate", "#8b1a1a"),
        ("range_violation_rate", "#e6842e"),
        ("duplicate_rate", "#6b7280"),
    ):
        values = [b["data_quality"].get(metric, 0.0) for b in batches]
        fig.add_trace(go.Bar(x=sequences, y=values, name=metric, marker_color=color))
    fig.update_layout(
        title="Data quality by batch",
        xaxis_title="Batch sequence",
        yaxis_title="Rate",
        barmode="group",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def feature_drift_heatmap_chart(batches: list[dict[str, Any]], metric: str = "psi") -> go.Figure:
    fig = go.Figure()
    scored = [b for b in batches if b.get("feature_drift")]
    if not scored:
        fig.update_layout(title=f"Feature drift heatmap ({metric}) - no data", **_LAYOUT_DEFAULTS)
        return fig
    features = [f["feature"] for f in scored[0]["feature_drift"]]
    z = []
    for feature in features:
        row = []
        for batch in scored:
            match = next((f for f in batch["feature_drift"] if f["feature"] == feature), None)
            row.append(match[metric] if match else None)
        z.append(row)
    fig.add_trace(
        go.Heatmap(
            z=z,
            x=[b["batch_sequence"] for b in scored],
            y=features,
            colorscale="Reds",
            colorbar={"title": metric.upper()},
        )
    )
    fig.update_layout(
        title=f"Feature drift heatmap ({metric.upper()})",
        xaxis_title="Batch sequence",
        yaxis_title="Feature",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def psi_ks_wasserstein_chart(batches: list[dict[str, Any]], feature: str) -> go.Figure:
    fig = go.Figure()
    scored = [b for b in batches if b.get("feature_drift")]
    if not scored:
        fig.update_layout(title=f"Drift metrics - {feature} (no data)", **_LAYOUT_DEFAULTS)
        return fig
    sequences, psi, ks, wasserstein = [], [], [], []
    for batch in scored:
        match = next((f for f in batch["feature_drift"] if f["feature"] == feature), None)
        if match is None:
            continue
        sequences.append(batch["batch_sequence"])
        psi.append(match["psi"])
        ks.append(match["ks_statistic"])
        wasserstein.append(match["wasserstein_distance"])
    fig.add_trace(
        go.Scatter(x=sequences, y=psi, mode="lines+markers", name="PSI", line={"color": "#1f5fa8"})
    )
    fig.add_trace(
        go.Scatter(x=sequences, y=ks, mode="lines+markers", name="KS", line={"color": "#8b1a1a"})
    )
    fig.add_trace(
        go.Scatter(
            x=sequences,
            y=wasserstein,
            mode="lines+markers",
            name="Wasserstein",
            line={"color": "#e6842e"},
        )
    )
    fig.update_layout(
        title=f"PSI / KS / Wasserstein - {feature}",
        xaxis_title="Batch sequence",
        yaxis_title="Value",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def score_distribution_chart(batches: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure()
    scored = [b for b in batches if b.get("score_drift")]
    if not scored:
        fig.update_layout(title="Score distribution shift (no data)", **_LAYOUT_DEFAULTS)
        return fig
    sequences = [b["batch_sequence"] for b in scored]
    batch_mean = [b["score_drift"]["batch_mean_score"] for b in scored]
    ref_mean = [b["score_drift"]["reference_mean_score"] for b in scored]
    fig.add_trace(
        go.Bar(x=sequences, y=batch_mean, name="Batch mean score", marker_color="#1f5fa8")
    )
    fig.add_trace(
        go.Scatter(
            x=sequences,
            y=ref_mean,
            mode="lines",
            name="Reference mean score",
            line={"color": "gray", "dash": "dash"},
        )
    )
    fig.update_layout(
        title="Score distribution - mean shift vs. reference",
        xaxis_title="Batch sequence",
        yaxis_title="Mean predicted P(default)",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def risk_band_shift_chart(batches: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure()
    scored = [b for b in batches if b.get("score_drift")]
    if not scored:
        fig.update_layout(title="Risk-band distribution shift (no data)", **_LAYOUT_DEFAULTS)
        return fig
    bands = ("low", "medium", "high", "very_high")
    colors = {"low": "#0e7c7b", "medium": "#1f5fa8", "high": "#e6842e", "very_high": "#8b1a1a"}
    sequences = [b["batch_sequence"] for b in scored]
    for band in bands:
        values = [b["score_drift"]["risk_band_distribution"].get(band, 0.0) for b in scored]
        fig.add_trace(go.Bar(x=sequences, y=values, name=band, marker_color=colors[band]))
    fig.update_layout(
        title="Risk-band distribution by batch",
        xaxis_title="Batch sequence",
        yaxis_title="Share",
        barmode="stack",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def performance_over_batches_chart(batches: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure()
    scored = [b for b in batches if isinstance(b.get("performance_drift"), dict)]
    if not scored:
        fig.update_layout(
            title="Performance over batch sequence (labels pending/blocked)", **_LAYOUT_DEFAULTS
        )
        return fig
    sequences = [b["batch_sequence"] for b in scored]
    roc_auc = [b["performance_drift"]["roc_auc"] for b in scored]
    pr_auc = [b["performance_drift"]["pr_auc"] for b in scored]
    fig.add_trace(
        go.Scatter(
            x=sequences, y=roc_auc, mode="lines+markers", name="ROC-AUC", line={"color": "#1f5fa8"}
        )
    )
    fig.add_trace(
        go.Scatter(
            x=sequences, y=pr_auc, mode="lines+markers", name="PR-AUC", line={"color": "#e6842e"}
        )
    )
    fig.update_layout(
        title="Performance over batch sequence",
        xaxis_title="Batch sequence",
        yaxis_title="Metric value",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def calibration_over_batches_chart(batches: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure()
    scored = [b for b in batches if isinstance(b.get("performance_drift"), dict)]
    if not scored:
        fig.update_layout(
            title="Calibration over batch sequence (labels pending/blocked)", **_LAYOUT_DEFAULTS
        )
        return fig
    sequences = [b["batch_sequence"] for b in scored]
    slope = [b["performance_drift"]["calibration_slope"] for b in scored]
    intercept = [b["performance_drift"]["calibration_intercept"] for b in scored]
    fig.add_trace(
        go.Scatter(
            x=sequences, y=slope, mode="lines+markers", name="Slope", line={"color": "#0e7c7b"}
        )
    )
    fig.add_trace(
        go.Scatter(
            x=sequences,
            y=intercept,
            mode="lines+markers",
            name="Intercept",
            line={"color": "#6a3d9a"},
        )
    )
    fig.add_hline(y=1.0, line_dash="dash", line_color="gray")
    fig.update_layout(
        title="Calibration slope/intercept over batch sequence",
        xaxis_title="Batch sequence",
        yaxis_title="Value",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def subgroup_composition_chart(batch: dict[str, Any] | None, attribute: str = "sex") -> go.Figure:
    fig = go.Figure()
    if not batch or not batch.get("subgroup_monitoring"):
        fig.update_layout(title="Subgroup composition (no data)", **_LAYOUT_DEFAULTS)
        return fig
    rows = [r for r in batch["subgroup_monitoring"] if r["attribute"] == attribute]
    if not rows:
        fig.update_layout(title=f"Subgroup composition - {attribute} (no data)", **_LAYOUT_DEFAULTS)
        return fig
    groups = [r["group"] for r in rows]
    fig.add_trace(
        go.Bar(
            x=groups, y=[r["composition_share"] for r in rows], name="Batch", marker_color="#1f5fa8"
        )
    )
    fig.add_trace(
        go.Bar(
            x=groups,
            y=[r["reference_composition_share"] for r in rows],
            name="Reference",
            marker_color="#6b7280",
        )
    )
    fig.update_layout(
        title=f"Subgroup composition - {attribute} (batch {batch['batch_sequence']})",
        xaxis_title="Group",
        yaxis_title="Share",
        barmode="group",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def subgroup_gaps_chart(batches: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure()
    rows = []
    for batch in batches:
        for attribute in ("sex", "education", "marriage"):
            groups = [
                r for r in batch.get("subgroup_monitoring", []) if r["attribute"] == attribute
            ]
            if len(groups) < 2:
                continue
            rates = [g["selection_rate"] for g in groups]
            rows.append(
                {
                    "batch_sequence": batch["batch_sequence"],
                    "attribute": attribute,
                    "gap": max(rates) - min(rates),
                }
            )
    if not rows:
        fig.update_layout(title="Subgroup selection-rate gaps (no data)", **_LAYOUT_DEFAULTS)
        return fig
    table = pd.DataFrame(rows)
    for attribute, color in (("sex", "#1f5fa8"), ("education", "#e6842e"), ("marriage", "#8b1a1a")):
        subset = table[table["attribute"] == attribute]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=subset["batch_sequence"],
                y=subset["gap"],
                mode="lines+markers",
                name=attribute,
                line={"color": color},
            )
        )
    fig.update_layout(
        title="Subgroup selection-rate gap (max - min) by batch",
        xaxis_title="Batch sequence",
        yaxis_title="absolute_gap",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def alert_timeline_chart(alerts: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure()
    if not alerts:
        fig.update_layout(title="Alert timeline (no alerts)", **_LAYOUT_DEFAULTS)
        return fig
    for severity, color in _SEVERITY_COLORS.items():
        subset = [a for a in alerts if a["severity"] == severity]
        if not subset:
            continue
        fig.add_trace(
            go.Scatter(
                x=[a["batch_sequence"] for a in subset],
                y=[a["category"] for a in subset],
                mode="markers",
                name=severity,
                marker={"color": color, "size": 10},
                text=[a["metric"] for a in subset],
            )
        )
    fig.update_layout(
        title="Alert timeline",
        xaxis_title="Batch sequence",
        yaxis_title="Category",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def validation_gates_chart(gates: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure()
    if not gates:
        fig.update_layout(title="Validation gates (no data)", **_LAYOUT_DEFAULTS)
        return fig
    colors = {"pass": "#0e7c7b", "warning": "#e6842e", "fail": "#8b1a1a"}
    fig.add_trace(
        go.Bar(
            x=[g["name"] for g in gates],
            y=[1] * len(gates),
            marker_color=[colors.get(g["status"], "#6b7280") for g in gates],
            text=[g["status"] for g in gates],
            textposition="inside",
        )
    )
    fig.update_layout(
        title="Independent validation gates",
        xaxis_title="Gate",
        yaxis_title="",
        showlegend=False,
        **_LAYOUT_DEFAULTS,
    )
    return fig


def pareto_tradeoff_chart(pareto: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if pareto.empty:
        fig.update_layout(title="Candidate/challenger trade-off (no data)", **_LAYOUT_DEFAULTS)
        return fig
    fig.add_trace(
        go.Scatter(
            x=pareto["scoring_latency_ms"],
            y=pareto["pr_auc"],
            mode="markers+text",
            text=pareto["model"],
            textposition="top center",
            marker={"size": 16, "color": ["#1f5fa8", "#e6842e"][: len(pareto)]},
        )
    )
    fig.update_layout(
        title="Candidate/challenger trade-off (PR-AUC vs. scoring latency)",
        xaxis_title="Scoring latency (ms)",
        yaxis_title="PR-AUC",
        **_LAYOUT_DEFAULTS,
    )
    return fig
