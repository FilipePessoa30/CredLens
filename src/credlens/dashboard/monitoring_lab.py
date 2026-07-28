"""Model Monitoring Lab page (Phase 9 section 22) - the 10th dashboard
page. Reads exclusively from `reports/monitoring/` and `reports/
model_validation/` - never rescoring a batch, never recomputing drift,
never accepting an uploaded file. Always labeled "Monitoring simulation
on a historical public benchmark" - never real production monitoring.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from credlens.dashboard import monitoring_charts as charts
from credlens.dashboard.components import empty_state
from credlens.modeling.provenance import NOT_SUITABLE_FOR_REAL_LENDING_EN, SEPARATION_NOTICE_EN
from credlens.monitoring.provenance import (
    MONITORING_SIMULATION_LABEL_EN,
    NOT_A_PRODUCTION_MONITORING_SYSTEM_EN,
)

_RUNS_DIR = Path("reports/monitoring/runs")
_ALERTS_DIR = Path("reports/monitoring/alerts")
_VALIDATION_DIR = Path("reports/model_validation")
_VALIDATION_TABLES_DIR = Path("reports/model_validation/tables")


@st.cache_data(show_spinner=False)
def _list_run_ids() -> list[str]:
    if not _RUNS_DIR.is_dir():
        return []
    return sorted(p.parent.name for p in _RUNS_DIR.glob("*/run.json"))


@st.cache_data(show_spinner=False)
def _load_run(run_id: str) -> dict[str, Any] | None:
    path = _RUNS_DIR / run_id / "run.json"
    if not path.is_file():
        return None
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return result


@st.cache_data(show_spinner=False)
def _load_alerts(run_id: str) -> list[dict[str, Any]]:
    path = _ALERTS_DIR / f"{run_id}.json"
    if not path.is_file():
        return []
    result: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return result


@st.cache_data(show_spinner=False)
def _load_decision() -> dict[str, Any] | None:
    path = _VALIDATION_DIR / "decision.json"
    if not path.is_file():
        return None
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return result


@st.cache_data(show_spinner=False)
def _load_pareto() -> pd.DataFrame:
    if not _VALIDATION_TABLES_DIR.is_dir():
        return pd.DataFrame()
    matches = sorted(_VALIDATION_TABLES_DIR.glob("*__pareto_comparison.csv"))
    if not matches:
        return pd.DataFrame()
    return pd.read_csv(matches[-1])


def render_monitoring_lab() -> None:
    st.header("Model Monitoring Lab")
    st.caption(f"Page provenance: {MONITORING_SIMULATION_LABEL_EN}")
    st.warning(NOT_A_PRODUCTION_MONITORING_SYSTEM_EN)
    st.caption(f"{SEPARATION_NOTICE_EN} {NOT_SUITABLE_FOR_REAL_LENDING_EN}")

    run_ids = _list_run_ids()
    if not run_ids:
        empty_state(
            "No monitoring run has been executed yet. Run 'credlens monitor create-reference "
            "--model-id <ID>', then 'simulate-batches', then 'run'."
        )
        return

    run_id = st.selectbox("Monitoring run", run_ids, index=len(run_ids) - 1)
    run_record = _load_run(run_id)
    if run_record is None:
        empty_state(f"Run '{run_id}' could not be loaded.")
        return
    alerts = _load_alerts(run_id)
    batches = run_record["batches"]

    st.caption(
        f"Reference: `{run_record['reference_id']}` | Batch set: `{run_record['batch_set_id']}` | "
        f"Model: `{run_record['model_id']}`"
    )
    col1, col2, col3 = st.columns(3)
    col1.metric("Batches", run_record["n_batches"])
    col2.metric("Alerts", run_record["n_alerts"])
    col3.metric("Blocked batches", sum(1 for b in batches if b["blocked"]))

    (
        tab_quality,
        tab_drift,
        tab_score,
        tab_performance,
        tab_subgroup,
        tab_alerts,
        tab_validation,
        tab_candidate,
    ) = st.tabs(
        [
            "Data Quality",
            "Feature Drift",
            "Score Drift",
            "Performance Drift",
            "Subgroup Monitoring",
            "Alerts",
            "Validation Decision",
            "Candidate/Challenger",
        ]
    )

    with tab_quality:
        st.plotly_chart(charts.data_quality_status_chart(batches), width="stretch")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "batch_sequence": b["batch_sequence"],
                        "scenario": b["simulation_scenario"],
                        "blocked": b["blocked"],
                        "n_rows": b["n_rows"],
                        "n_quarantined": b["n_quarantined"],
                        **b["data_quality"],
                    }
                    for b in batches
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    with tab_drift:
        st.plotly_chart(charts.feature_drift_heatmap_chart(batches), width="stretch")
        scored = [b for b in batches if b.get("feature_drift")]
        if scored:
            feature_names = [f["feature"] for f in scored[0]["feature_drift"]]
            feature = st.selectbox("Feature", feature_names)
            st.plotly_chart(charts.psi_ks_wasserstein_chart(batches, feature), width="stretch")
        else:
            empty_state("No scored batch has feature drift yet.")

    with tab_score:
        st.plotly_chart(charts.score_distribution_chart(batches), width="stretch")
        st.plotly_chart(charts.risk_band_shift_chart(batches), width="stretch")

    with tab_performance:
        st.caption("Only computed for batches with label_availability='available'.")
        st.plotly_chart(charts.performance_over_batches_chart(batches), width="stretch")
        st.plotly_chart(charts.calibration_over_batches_chart(batches), width="stretch")

    with tab_subgroup:
        st.caption(
            "Fairness and subgroup diagnostics - not a compliance assessment. No threshold is "
            "adjusted per group."
        )
        scored = [b for b in batches if b.get("subgroup_monitoring")]
        if scored:
            batch_choice = st.selectbox(
                "Batch", [b["batch_sequence"] for b in scored], format_func=lambda s: f"Batch {s}"
            )
            selected_batch = next(b for b in scored if b["batch_sequence"] == batch_choice)
            attribute = st.selectbox("Attribute", ["sex", "education", "marriage"])
            st.plotly_chart(
                charts.subgroup_composition_chart(selected_batch, attribute), width="stretch"
            )
        st.plotly_chart(charts.subgroup_gaps_chart(batches), width="stretch")

    with tab_alerts:
        st.plotly_chart(charts.alert_timeline_chart(alerts), width="stretch")
        if alerts:
            st.dataframe(pd.DataFrame(alerts), width="stretch", hide_index=True)
        else:
            empty_state("No alerts were raised in this run.")

    with tab_validation:
        decision = _load_decision()
        if decision is None:
            empty_state("Run 'credlens model validate-independent' to populate this section.")
        else:
            st.info(f"Decision: **{decision['decision']}** - {decision['reason']}")
            st.plotly_chart(charts.validation_gates_chart(decision["gates"]), width="stretch")
            st.dataframe(pd.DataFrame(decision["gates"]), width="stretch", hide_index=True)

    with tab_candidate:
        pareto = _load_pareto()
        if pareto.empty:
            empty_state("Run 'credlens model compare-candidates' to populate this section.")
        else:
            st.plotly_chart(charts.pareto_tradeoff_chart(pareto), width="stretch")
            st.dataframe(pareto, width="stretch", hide_index=True)
