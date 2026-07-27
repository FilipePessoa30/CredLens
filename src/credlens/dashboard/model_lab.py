"""Model Lab page (Phase 8 section 27) - the 9th dashboard page.

Provenance: `Historical public benchmark - UCI, Taiwan, 2005`. This page
NEVER shares numbers with the synthetic CredLens portfolio pages - it
reads exclusively from `reports/modeling/` (experiment records + tables
already written by `credlens model train/evaluate/explain/audit-groups/
stress-test/register/report`), never recomputing a metric, never
retraining, never accepting an uploaded file. If no experiment has been
run yet, it shows an empty state, never a stack trace.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from credlens.dashboard import model_charts as charts
from credlens.dashboard.components import empty_state
from credlens.modeling.provenance import (
    MODEL_LAB_PROVENANCE_LABEL_EN,
    NOT_SUITABLE_FOR_REAL_LENDING_EN,
    SEPARATION_NOTICE_EN,
)

_EXPERIMENTS_DIR = Path("reports/modeling/experiments")
_TABLES_DIR = Path("reports/modeling/tables")
_MODELING_ROOT = Path("reports/modeling")
_ALL_MODEL_KINDS = ("dummy_prior", "simple_rule", "logistic_regression", "hist_gradient_boosting")


@st.cache_data(show_spinner=False)
def _list_experiment_ids() -> list[str]:
    if not _EXPERIMENTS_DIR.is_dir():
        return []
    return sorted(p.stem for p in _EXPERIMENTS_DIR.glob("*.json"))


@st.cache_data(show_spinner=False)
def _load_experiment(experiment_id: str) -> dict[str, Any] | None:
    path = _EXPERIMENTS_DIR / f"{experiment_id}.json"
    if not path.is_file():
        return None
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return result


@st.cache_data(show_spinner=False)
def _load_table(experiment_id: str, name: str) -> pd.DataFrame:
    path = _TABLES_DIR / f"{experiment_id}__{name}.csv"
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path)


@st.cache_data(show_spinner=False)
def _load_json_table(experiment_id: str, name: str) -> Any:
    path = _TABLES_DIR / f"{experiment_id}__{name}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def render_model_lab() -> None:
    st.header("Model Lab")
    st.caption(f"Page provenance: {MODEL_LAB_PROVENANCE_LABEL_EN}")
    st.warning(SEPARATION_NOTICE_EN)
    st.caption(
        "Behavioral early-warning model for next-month default - NOT an origination score, "
        "NOT a real lending decision, NOT connected to the synthetic CredLens portfolio."
    )

    experiment_ids = _list_experiment_ids()
    if not experiment_ids:
        empty_state(
            "No modeling experiment has been run yet. Run 'credlens model train --experiment-id "
            "<ID>' followed by 'evaluate'/'explain'/'audit-groups'/'stress-test'/'register'."
        )
        return

    experiment_id = st.selectbox("Experiment", experiment_ids, index=len(experiment_ids) - 1)
    experiment = _load_experiment(experiment_id)
    if experiment is None or experiment.get("status") not in (
        "evaluated",
        "registered_candidate",
        "gates_failed",
    ):
        empty_state(
            f"Experiment '{experiment_id}' has not been evaluated yet - run 'credlens model "
            "evaluate' first."
        )
        return

    predictions_test = _load_table(experiment_id, "predictions_test")
    if predictions_test.empty:
        empty_state("No test predictions found for this experiment.")
        return

    available_kinds = [k for k in _ALL_MODEL_KINDS if k in predictions_test.columns]
    main_kind = (
        "logistic_regression" if "logistic_regression" in available_kinds else available_kinds[0]
    )

    (
        tab_overview,
        tab_compare,
        tab_ranking,
        tab_calibration,
        tab_capacity,
        tab_interpret,
        tab_subgroup,
        tab_robustness,
        tab_card,
    ) = st.tabs(
        [
            "Overview",
            "Champion/Challenger",
            "Discrimination & Ranking",
            "Calibration",
            "Capacity Simulator",
            "Interpretability",
            "Subgroup Diagnostics",
            "Robustness & Stability",
            "Model Card",
        ]
    )

    test_metrics = experiment.get("metrics", {}).get("test", {}).get(main_kind, {})

    with tab_overview:
        col1, col2, col3 = st.columns(3)
        col1.metric("Prevalence (test)", f"{test_metrics.get('prevalence', 0):.2%}")
        col2.metric(
            "ROC-AUC (test)", f"{test_metrics.get('discrimination', {}).get('roc_auc', 0):.4f}"
        )
        col3.metric(
            "PR-AUC (test)", f"{test_metrics.get('discrimination', {}).get('pr_auc', 0):.4f}"
        )
        st.caption(f"Dataset hash: `{experiment.get('dataset_hash', '')[:16]}...`")
        split_hash = experiment.get("split_hash", "")[:16]
        st.caption(f"Split hash: `{split_hash}...`  |  seed={experiment.get('seed')}")
        st.info(f"Status: **{experiment.get('status')}**. {NOT_SUITABLE_FOR_REAL_LENDING_EN}")

    with tab_compare:
        champ = _load_table(experiment_id, "champion_challenger")
        if champ.empty:
            empty_state("Run 'credlens model compare' to populate this table.")
        else:
            st.plotly_chart(charts.champion_challenger_chart(champ), width="stretch")
            st.dataframe(champ, width="stretch", hide_index=True)

    with tab_ranking:
        st.plotly_chart(charts.roc_curve_chart(predictions_test, available_kinds), width="stretch")
        st.plotly_chart(
            charts.precision_recall_chart(predictions_test, available_kinds), width="stretch"
        )
        decile_table = test_metrics.get("ranking", {}).get("decile_table", [])
        col_a, col_b = st.columns(2)
        with col_a:
            st.plotly_chart(charts.decile_lift_chart(decile_table), width="stretch")
        with col_b:
            st.plotly_chart(charts.cumulative_gains_chart(decile_table), width="stretch")
        st.plotly_chart(
            charts.event_rate_by_decile_chart(decile_table, test_metrics.get("prevalence", 0.0)),
            width="stretch",
        )

    with tab_calibration:
        st.plotly_chart(charts.calibration_chart(predictions_test, main_kind), width="stretch")
        cal = test_metrics.get("calibration", {})
        st.dataframe(pd.DataFrame([cal]), width="stretch", hide_index=True)
        selected_method = experiment.get("calibration", {}).get("selected_method")
        st.caption(f"Calibration method selected: {selected_method}")

    with tab_capacity:
        thresholds_table = _load_table(experiment_id, "thresholds")
        if thresholds_table.empty:
            empty_state("Run 'credlens model evaluate' to populate operating points.")
        else:
            st.caption(
                "Illustrative review-capacity scenario - never a profit-optimized threshold, "
                "never a recommended policy. One fixed threshold at a time, never per group."
            )
            point_name = st.selectbox("Operating point", thresholds_table["name"].tolist())
            row = thresholds_table[thresholds_table["name"] == point_name].iloc[0].to_dict()
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Population reviewed", f"{row['n_flagged']:,} / {row['n_total']:,}")
            col2.metric("Recall (capture rate)", f"{row['recall']:.1%}")
            col3.metric("Precision", f"{row['precision']:.1%}")
            col4.metric("False positives", f"{row['false_positive']:,}")
            st.plotly_chart(charts.confusion_matrix_chart(row), width="stretch")

    with tab_interpret:
        coefficients = _load_table(experiment_id, "coefficients")
        permutation = _load_table(experiment_id, "permutation_importance")
        col1, col2 = st.columns(2)
        with col1:
            if coefficients.empty:
                empty_state("Run 'credlens model explain' to populate coefficients.")
            else:
                st.plotly_chart(charts.coefficients_chart(coefficients), width="stretch")
        with col2:
            if permutation.empty:
                empty_state("Run 'credlens model explain' to populate permutation importance.")
            else:
                st.plotly_chart(charts.permutation_importance_chart(permutation), width="stretch")

        pdp = _load_table(experiment_id, "partial_dependence")
        if not pdp.empty:
            feature = st.selectbox("Partial dependence feature", pdp["feature"].unique().tolist())
            st.plotly_chart(charts.partial_dependence_chart(pdp, feature), width="stretch")

        local_explanations = _load_json_table(experiment_id, "local_explanations")
        if local_explanations:
            case_labels = [c["case_label"] for c in local_explanations]
            selected_case = st.selectbox("Representative case", case_labels)
            case = next(c for c in local_explanations if c["case_label"] == selected_case)
            st.caption(
                f"Pseudonymous ID: {case['pseudonymous_id']} | "
                f"Predicted P(default)={case['predicted_probability']:.3f} | "
                f"Actual label={case['actual_label']}"
            )
            st.dataframe(pd.DataFrame(case["reason_codes"]), width="stretch", hide_index=True)
            st.caption(case.get("note_en", ""))

    with tab_subgroup:
        subgroup_table = _load_table(experiment_id, "subgroup_audit")
        if subgroup_table.empty:
            empty_state("Run 'credlens model audit-groups' to populate this section.")
        else:
            st.caption(
                "Fairness and subgroup diagnostics - NOT a compliance assessment. One fixed "
                "threshold for every group; groups with insufficient sample are shown for audit "
                "only, never ranked."
            )
            metric_choice = st.selectbox(
                "Metric", ["roc_auc", "true_positive_rate", "selection_rate"]
            )
            st.plotly_chart(charts.subgroup_chart(subgroup_table, metric_choice), width="stretch")
            st.dataframe(subgroup_table, width="stretch", hide_index=True)

    with tab_robustness:
        robustness_table = _load_table(experiment_id, "robustness")
        stability_table = _load_table(experiment_id, "split_stability")
        if robustness_table.empty:
            empty_state("Run 'credlens model stress-test' to populate this section.")
        else:
            st.plotly_chart(charts.robustness_chart(robustness_table), width="stretch")
            st.dataframe(robustness_table, width="stretch", hide_index=True)
        if not stability_table.empty:
            st.plotly_chart(charts.seed_stability_chart(stability_table), width="stretch")

    with tab_card:
        model_card_path = _MODELING_ROOT / "model_card.md"
        if model_card_path.is_file():
            st.markdown(model_card_path.read_text(encoding="utf-8"))
        else:
            empty_state("Run 'credlens model report' to generate the model card.")
