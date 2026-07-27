"""Interactive Plotly charts for the Model Lab page (Phase 8 section 27,
29). Every function here takes already-computed values (a persisted
predictions table, a decile table already written by
`credlens.modeling.reporting`, ...) - it never re-fits or re-scores a
model. Deriving a ROC/PR/calibration curve from an already-scored
prediction column is a pure mathematical view of validated output, not a
recalculation of any business rule or model.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go

MODEL_COLORS: dict[str, str] = {
    "dummy_prior": "#6b7280",
    "simple_rule": "#0e7c7b",
    "logistic_regression": "#1f5fa8",
    "hist_gradient_boosting": "#e6842e",
}

_LAYOUT_DEFAULTS: dict[str, Any] = {
    "template": "plotly_white",
    "margin": {"l": 40, "r": 20, "t": 50, "b": 40},
    "hovermode": "closest",
    "legend": {"orientation": "h", "y": -0.2},
}


def _color_for(model_kind: str) -> str:
    return MODEL_COLORS.get(model_kind, "#888888")


def roc_curve_chart(predictions: pd.DataFrame, model_kinds: list[str]) -> go.Figure:
    from sklearn.metrics import roc_curve

    fig = go.Figure()
    y_true = predictions["y_true"]
    for kind in model_kinds:
        if kind not in predictions.columns:
            continue
        fpr, tpr, _ = roc_curve(y_true, predictions[kind])
        fig.add_trace(
            go.Scatter(x=fpr, y=tpr, mode="lines", name=kind, line={"color": _color_for(kind)})
        )
    fig.add_trace(
        go.Scatter(
            x=[0, 1], y=[0, 1], mode="lines", name="Random", line={"dash": "dash", "color": "gray"}
        )
    )
    fig.update_layout(
        title="ROC curve (test)",
        xaxis_title="False positive rate",
        yaxis_title="True positive rate",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def precision_recall_chart(predictions: pd.DataFrame, model_kinds: list[str]) -> go.Figure:
    from sklearn.metrics import precision_recall_curve

    fig = go.Figure()
    y_true = predictions["y_true"]
    prevalence = float(y_true.mean()) if len(y_true) else 0.0
    for kind in model_kinds:
        if kind not in predictions.columns:
            continue
        precision, recall, _ = precision_recall_curve(y_true, predictions[kind])
        fig.add_trace(
            go.Scatter(
                x=recall, y=precision, mode="lines", name=kind, line={"color": _color_for(kind)}
            )
        )
    fig.add_hline(
        y=prevalence, line_dash="dash", line_color="gray", annotation_text="No-skill baseline"
    )
    fig.update_layout(
        title="Precision-recall curve (test)",
        xaxis_title="Recall",
        yaxis_title="Precision",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def calibration_chart(predictions: pd.DataFrame, model_kind: str, n_bins: int = 10) -> go.Figure:
    from sklearn.calibration import calibration_curve

    fig = go.Figure()
    if model_kind not in predictions.columns:
        fig.update_layout(title="Calibration curve", **_LAYOUT_DEFAULTS)
        return fig
    frac_pos, mean_pred = calibration_curve(
        predictions["y_true"], predictions[model_kind], n_bins=n_bins, strategy="quantile"
    )
    fig.add_trace(
        go.Scatter(
            x=mean_pred,
            y=frac_pos,
            mode="lines+markers",
            name=model_kind,
            line={"color": _color_for(model_kind)},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[0, 1], y=[0, 1], mode="lines", name="Perfect", line={"dash": "dash", "color": "gray"}
        )
    )
    fig.update_layout(
        title="Calibration curve (test)",
        xaxis_title="Mean predicted probability",
        yaxis_title="Observed event rate",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def decile_lift_chart(decile_table: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure()
    if not decile_table:
        fig.update_layout(title="Lift by decile", **_LAYOUT_DEFAULTS)
        return fig
    df = pd.DataFrame(decile_table)
    fig.add_trace(go.Bar(x=df["decile"], y=df["lift"], marker_color="#e6842e"))
    fig.add_hline(y=1.0, line_dash="dash", line_color="gray")
    fig.update_layout(
        title="Lift by decile (1 = highest predicted risk)",
        xaxis_title="Decile",
        yaxis_title="Lift",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def cumulative_gains_chart(decile_table: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure()
    if not decile_table:
        fig.update_layout(title="Cumulative gains", **_LAYOUT_DEFAULTS)
        return fig
    df = pd.DataFrame(decile_table)
    fig.add_trace(
        go.Scatter(
            x=df["cumulative_population_share"],
            y=df["cumulative_capture_rate"],
            mode="lines+markers",
            name="Model",
            line={"color": "#1f5fa8"},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[0, 1], y=[0, 1], mode="lines", name="Random", line={"dash": "dash", "color": "gray"}
        )
    )
    fig.update_layout(
        title="Cumulative gains",
        xaxis_title="Cumulative population share",
        yaxis_title="Cumulative capture rate",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def event_rate_by_decile_chart(
    decile_table: list[dict[str, Any]], overall_prevalence: float
) -> go.Figure:
    fig = go.Figure()
    if not decile_table:
        fig.update_layout(title="Event rate by decile", **_LAYOUT_DEFAULTS)
        return fig
    df = pd.DataFrame(decile_table)
    fig.add_trace(go.Bar(x=df["decile"], y=df["event_rate"], marker_color="#8b1a1a"))
    fig.add_hline(
        y=overall_prevalence,
        line_dash="dash",
        line_color="gray",
        annotation_text="Overall prevalence",
    )
    fig.update_layout(
        title="Event rate by decile",
        xaxis_title="Decile",
        yaxis_title="Observed event rate",
        yaxis_tickformat=".1%",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def confusion_matrix_chart(operating_point: dict[str, Any]) -> go.Figure:
    matrix = [
        [operating_point["true_negative"], operating_point["false_positive"]],
        [operating_point["false_negative"], operating_point["true_positive"]],
    ]
    fig = go.Figure(
        data=go.Heatmap(
            z=matrix,
            x=["Predicted 0", "Predicted 1"],
            y=["Actual 0", "Actual 1"],
            colorscale="Blues",
            text=matrix,
            texttemplate="%{text}",
        )
    )
    fig.update_layout(
        title=f"Confusion matrix (threshold={operating_point['threshold']:.3f})", **_LAYOUT_DEFAULTS
    )
    return fig


def champion_challenger_chart(table: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if table.empty:
        fig.update_layout(title="Champion/challenger comparison", **_LAYOUT_DEFAULTS)
        return fig
    fig.add_trace(
        go.Bar(x=table["model"], y=table["roc_auc"], name="ROC-AUC", marker_color="#1f5fa8")
    )
    fig.add_trace(
        go.Bar(x=table["model"], y=table["pr_auc"], name="PR-AUC", marker_color="#e6842e")
    )
    fig.update_layout(
        title="Champion/challenger comparison (test)", barmode="group", **_LAYOUT_DEFAULTS
    )
    return fig


def coefficients_chart(table: pd.DataFrame, top_n: int = 10) -> go.Figure:
    fig = go.Figure()
    if table.empty:
        fig.update_layout(title="Logistic regression coefficients", **_LAYOUT_DEFAULTS)
        return fig
    top = table.head(top_n).iloc[::-1]
    colors = ["#8b1a1a" if v > 0 else "#0e7c7b" for v in top["coefficient"]]
    fig.add_trace(
        go.Bar(x=top["coefficient"], y=top["feature"], orientation="h", marker_color=colors)
    )
    fig.update_layout(
        title="Logistic regression coefficients (standardized)",
        xaxis_title="Coefficient",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def permutation_importance_chart(table: pd.DataFrame, top_n: int = 10) -> go.Figure:
    fig = go.Figure()
    if table.empty:
        fig.update_layout(title="Permutation importance", **_LAYOUT_DEFAULTS)
        return fig
    top = table.head(top_n).iloc[::-1]
    fig.add_trace(
        go.Bar(
            x=top["mean_importance"],
            y=top["feature"],
            orientation="h",
            marker_color="#1f5fa8",
            error_x={"type": "data", "array": top["stdev_importance"]},
        )
    )
    fig.update_layout(
        title="Permutation importance (average precision)",
        xaxis_title="Importance",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def partial_dependence_chart(table: pd.DataFrame, feature: str) -> go.Figure:
    fig = go.Figure()
    subset = table[table["feature"] == feature] if not table.empty else table
    if subset.empty:
        fig.update_layout(title="Partial dependence", **_LAYOUT_DEFAULTS)
        return fig
    fig.add_trace(
        go.Scatter(
            x=subset["grid_value"],
            y=subset["average_prediction"],
            mode="lines",
            line={"color": "#6a3d9a"},
        )
    )
    fig.update_layout(
        title=f"Partial dependence - {feature} (association, not causation)",
        xaxis_title="Feature value",
        yaxis_title="Average predicted P(default)",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def subgroup_chart(table: pd.DataFrame, metric: str = "roc_auc") -> go.Figure:
    fig = go.Figure()
    if table.empty:
        fig.update_layout(title="Subgroup diagnostics", **_LAYOUT_DEFAULTS)
        return fig
    plotted = table.dropna(subset=[metric])
    colors = [
        "#6b7280" if c == "insufficient" else "#1f5fa8" for c in plotted["sample_classification"]
    ]
    labels = [
        f"{a}={g} (n={n})"
        for a, g, n in zip(plotted["attribute"], plotted["group"], plotted["n"], strict=True)
    ]
    fig.add_trace(go.Bar(x=plotted[metric], y=labels, orientation="h", marker_color=colors))
    fig.update_layout(
        title=f"Subgroup diagnostics - {metric} (not a compliance assessment)",
        xaxis_title=metric,
        **_LAYOUT_DEFAULTS,
    )
    return fig


def robustness_chart(table: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if table.empty:
        fig.update_layout(title="Robustness under perturbation", **_LAYOUT_DEFAULTS)
        return fig
    fig.add_trace(
        go.Bar(
            x=table["pr_auc_degradation"], y=table["kind"], orientation="h", marker_color="#e6842e"
        )
    )
    fig.update_layout(
        title="PR-AUC degradation under controlled perturbations",
        xaxis_title="PR-AUC degradation",
        **_LAYOUT_DEFAULTS,
    )
    return fig


def seed_stability_chart(table: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if table.empty:
        fig.update_layout(title="Stability across split seeds", **_LAYOUT_DEFAULTS)
        return fig
    fig.add_trace(
        go.Scatter(
            x=table["seed"],
            y=table["roc_auc"],
            mode="markers",
            marker={"color": "#1f5fa8", "size": 10},
        )
    )
    fig.add_hline(
        y=table["roc_auc"].mean(), line_dash="dash", line_color="gray", annotation_text="Mean"
    )
    fig.update_layout(
        title="Stability across independent split seeds",
        xaxis_title="Split seed",
        yaxis_title="Test ROC-AUC",
        **_LAYOUT_DEFAULTS,
    )
    return fig
