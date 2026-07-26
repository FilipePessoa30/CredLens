"""Page render functions (Phase 7 section 11) - the actual composition
logic for each of the 8 required dashboard pages. Kept separate from the
thin `dashboard/pages/*.py` Streamlit entrypoint scripts so this module
is independently unit-testable and so `streamlit.testing.v1.AppTest` can
drive each page through its own thin script.

No page recomputes a KPI - every number comes from `data.tables` (already
queried by `credlens.analysis.metrics`/`scenarios`) or the insights/
robustness registries, reshaped for display by `credlens.dashboard.
queries` and formatted by `credlens.dashboard.formatting`.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from credlens.analysis.data_provenance import get_figure_provenance, get_table_provenance
from credlens.analysis.sample_policy import classify_sample_size
from credlens.dashboard import charts, queries
from credlens.dashboard.components import (
    empty_state,
    kpi_card,
    methodology_link,
    render_insight_summary,
    render_provenance_caption,
    render_sample_warning,
    sample_badge,
    synthetic_warning_banner,
)
from credlens.dashboard.data_access import DashboardData, load_robustness_report
from credlens.dashboard.filters import FilterState, apply_filters, is_empty_result
from credlens.dashboard.formatting import (
    format_count,
    format_delta_abs,
    format_percent,
    format_synthetic_money,
    safe_ratio,
)
from credlens.dashboard.provenance import page_provenance_category


def _get(data: DashboardData, name: str) -> Any:
    import pandas as pd

    return data.tables.get(name, pd.DataFrame())


def _page_provenance_badge(page_key: str) -> None:
    """A page-level, at-a-glance provenance signal (Phase 7 gate C) -
    distinct from and in addition to the per-table/per-figure captions
    each page already renders further down."""
    from credlens.analysis.data_provenance import LABELS_EN

    category = page_provenance_category(page_key)
    st.caption(f"Page provenance: {LABELS_EN[category]}")


# --- 1. Executive Overview ---------------------------------------------------


def render_executive_overview(data: DashboardData, state: FilterState) -> None:
    st.header("Executive Overview")
    _page_provenance_badge("executive_overview")
    synthetic_warning_banner()

    funnel = apply_filters(_get(data, "funnel_monthly"), state)
    portfolio = apply_filters(_get(data, "portfolio_monthly"), state)
    delinquency = apply_filters(_get(data, "delinquency_monthly"), state)
    scenario_cmp = _get(data, "scenario_comparison")

    if is_empty_result(funnel) and is_empty_result(portfolio):
        empty_state("Try widening the scenario/date/channel filters in the sidebar.")
        return

    totals = queries.approval_and_booking_rates(
        queries.totals_by_scenario(
            funnel,
            ["applications_submitted", "decisioned_applications", "approved_count", "booked_count"],
        )
    )
    latest_portfolio = queries.latest_snapshot_per_scenario(portfolio)
    latest_delinquency = queries.latest_snapshot_per_scenario(delinquency)

    baseline_row = totals[totals["scenario"] == "baseline"] if not totals.empty else totals
    n_applications = (
        int(baseline_row["applications_submitted"].iloc[0]) if not baseline_row.empty else None
    )

    cols = st.columns(4)
    with cols[0]:
        kpi_card(
            "Applications (baseline)",
            format_count(n_applications) if n_applications is not None else "n/a",
        )
    with cols[1]:
        approval = (
            float(baseline_row["approval_rate"].iloc[0])
            if not baseline_row.empty and baseline_row["approval_rate"].iloc[0] is not None
            else None
        )
        kpi_card(
            "Approval rate (baseline)", format_percent(approval) if approval is not None else "n/a"
        )
    with cols[2]:
        booking = (
            float(baseline_row["booking_rate"].iloc[0])
            if not baseline_row.empty and baseline_row["booking_rate"].iloc[0] is not None
            else None
        )
        kpi_card(
            "Booking rate of approved (baseline)",
            format_percent(booking) if booking is not None else "n/a",
        )
    with cols[3]:
        active = (
            int(
                latest_portfolio[latest_portfolio["scenario"] == "baseline"][
                    "active_contracts"
                ].iloc[0]
            )
            if not latest_portfolio.empty
            and "baseline" in set(latest_portfolio.get("scenario", []))
            else None
        )
        kpi_card(
            "Active contracts (baseline)", format_count(active) if active is not None else "n/a"
        )

    cols2 = st.columns(4)
    base_bal = (
        latest_portfolio[latest_portfolio["scenario"] == "baseline"]
        if not latest_portfolio.empty
        else latest_portfolio
    )
    base_del = (
        latest_delinquency[latest_delinquency["scenario"] == "baseline"]
        if not latest_delinquency.empty
        else latest_delinquency
    )
    with cols2[0]:
        balance = float(base_bal["outstanding_balance"].iloc[0]) if not base_bal.empty else None
        kpi_card(
            "Outstanding balance (baseline)",
            format_synthetic_money(balance) if balance is not None else "n/a",
        )
    with cols2[1]:
        par30 = float(base_del["par30"].iloc[0]) if not base_del.empty else None
        kpi_card("PAR30 (baseline)", format_percent(par30) if par30 is not None else "n/a")
    with cols2[2]:
        par90 = float(base_del["par90"].iloc[0]) if not base_del.empty else None
        kpi_card("PAR90 (baseline)", format_percent(par90) if par90 is not None else "n/a")
    with cols2[3]:
        cure_rate = float(base_del["cure_rate"].iloc[0]) if not base_del.empty else None
        kpi_card(
            "Cure rate, latest month (baseline)",
            format_percent(cure_rate) if cure_rate is not None else "n/a",
        )

    sample_n = n_applications
    sample_class = classify_sample_size(sample_n) if sample_n is not None else None
    st.caption(sample_badge(sample_n, sample_class))
    render_sample_warning(sample_n, sample_class)

    if not scenario_cmp.empty:
        st.subheader("Scenario comparison (whole run)")
        st.dataframe(scenario_cmp, width="stretch")

    st.subheader("Validated insights")
    render_insight_summary(data.insights)

    render_provenance_caption(get_table_provenance("portfolio_monthly"))
    methodology_link()


# --- 2. Credit Funnel ---------------------------------------------------


def render_credit_funnel(data: DashboardData, state: FilterState) -> None:
    st.header("Credit Funnel")
    _page_provenance_badge("credit_funnel")
    synthetic_warning_banner()

    funnel = apply_filters(_get(data, "funnel_monthly"), state)
    if is_empty_result(funnel):
        empty_state("No funnel rows match the current filters.")
        return

    st.plotly_chart(charts.funnel_by_scenario(funnel), width="stretch")

    totals = queries.approval_and_booking_rates(
        queries.totals_by_scenario(
            funnel,
            [
                "applications_submitted",
                "decisioned_applications",
                "approved_count",
                "rejected_count",
                "booked_count",
            ],
        )
    )
    if not totals.empty:
        totals["approved_not_booked"] = totals["approved_count"] - totals["booked_count"]
        st.subheader("Totals by scenario")
        st.dataframe(totals, width="stretch")

    by_channel = apply_filters(_get(data, "funnel_by_channel_and_scenario"), state)
    if not is_empty_result(by_channel):
        st.subheader("By channel")
        for _, row in by_channel.iterrows():
            render_sample_warning(
                int(row["decisioned_applications"]), row.get("sample_classification")
            )
            break
        st.dataframe(by_channel, width="stretch")

    by_policy = apply_filters(_get(data, "policy_version_comparison"), state)
    if not is_empty_result(by_policy):
        st.subheader("By policy version")
        st.dataframe(by_policy, width="stretch")

    segment = apply_filters(_get(data, "credit_risk_segment_summary"), state)
    if not is_empty_result(segment):
        st.subheader("By bureau score / income / contract-value band")
        st.dataframe(segment, width="stretch")

    render_provenance_caption(get_figure_provenance("credit_funnel"))
    methodology_link()


# --- 3. Portfolio & Delinquency ---------------------------------------------------


def render_portfolio_delinquency(data: DashboardData, state: FilterState) -> None:
    st.header("Portfolio & Delinquency")
    _page_provenance_badge("portfolio_delinquency")
    synthetic_warning_banner()

    portfolio = apply_filters(_get(data, "portfolio_monthly"), state)
    delinquency = apply_filters(_get(data, "delinquency_monthly"), state)
    if is_empty_result(portfolio) and is_empty_result(delinquency):
        empty_state("No portfolio/delinquency rows match the current filters.")
        return

    if not portfolio.empty:
        st.plotly_chart(
            charts.line_by_scenario(
                portfolio,
                "snapshot_date",
                "outstanding_balance",
                title="Outstanding Balance Over Time",
                y_label="Synthetic monetary units",
            ),
            width="stretch",
        )
        latest = queries.latest_snapshot_per_scenario(portfolio)
        if not latest.empty:
            latest = latest.copy()
            latest["paid_to_scheduled_ratio_pct"] = latest["paid_to_scheduled_ratio"]
            st.dataframe(
                latest[
                    [
                        "scenario",
                        "snapshot_date",
                        "active_contracts",
                        "outstanding_balance",
                        "avg_ticket",
                        "scheduled_amount_due_this_month",
                        "paid_to_scheduled_ratio_pct",
                    ]
                ],
                width="stretch",
            )

    if not delinquency.empty:
        st.plotly_chart(
            charts.line_by_scenario(
                delinquency,
                "snapshot_date",
                "par90",
                title="PAR90 Over Time",
                y_label="Fraction of balance",
                y_is_percent=True,
            ),
            width="stretch",
        )
        latest_del = queries.latest_snapshot_per_scenario(delinquency)
        if not latest_del.empty:
            st.subheader("DPD buckets - count vs. balance at risk (latest snapshot)")
            display = latest_del[
                [
                    "scenario",
                    "snapshot_date",
                    "contracts_30plus",
                    "contracts_60plus",
                    "contracts_90plus",
                    "balance_30plus",
                    "balance_60plus",
                    "balance_90plus",
                    "par30",
                    "par60",
                    "par90",
                ]
            ]
            st.dataframe(display, width="stretch")

    render_provenance_caption(get_table_provenance("portfolio_monthly"))
    methodology_link()


# --- 4. Vintages & Roll Rates ---------------------------------------------------


def render_vintages_roll_rates(data: DashboardData, state: FilterState) -> None:
    st.header("Vintages & Roll Rates")
    _page_provenance_badge("vintages_roll_rates")
    synthetic_warning_banner()

    vintage = apply_filters(_get(data, "vintage_cohorts"), state)
    roll_rates = apply_filters(_get(data, "roll_rates"), state)
    if is_empty_result(vintage) and is_empty_result(roll_rates):
        empty_state("No vintage/roll-rate rows match the current filters.")
        return

    scenario = state.scenarios[0] if state.scenarios else "baseline"
    if not vintage.empty:
        st.plotly_chart(charts.vintage_curves(vintage, scenario), width="stretch")
        most_mature = queries.most_mature_comparable_mob(vintage)
        if most_mature is not None:
            st.caption(
                f"Cohorts are only compared up to months_on_book={most_mature} - the "
                "largest MOB every cohort has reached. Younger cohorts are immature at "
                "higher MOB and excluded from that comparison."
            )

    if not roll_rates.empty:
        st.plotly_chart(charts.roll_rate_heatmap(roll_rates), width="stretch")
        rate = queries.roll_forward_rate_from_current(roll_rates)
        if rate is not None:
            st.metric("Roll-forward rate from 'current'", format_percent(rate))

    render_provenance_caption(get_figure_provenance("vintage_curves"))
    methodology_link()


# --- 5. Cure, Collections & Recovery ---------------------------------------------------


def render_cure_collections_recovery(data: DashboardData, state: FilterState) -> None:
    st.header("Cure, Collections & Recovery")
    _page_provenance_badge("cure_collections_recovery")
    synthetic_warning_banner()

    delinquency = apply_filters(_get(data, "delinquency_monthly"), state)
    collections = apply_filters(_get(data, "collections_performance"), state)
    writeoff = apply_filters(_get(data, "writeoff_recovery"), state)
    cure_summary = apply_filters(_get(data, "cure_and_redefault"), state)

    if is_empty_result(delinquency) and is_empty_result(collections) and is_empty_result(writeoff):
        empty_state("No cure/collections/write-off rows match the current filters.")
        return

    if not delinquency.empty:
        st.subheader("New delinquencies, cures, relapses (per month)")
        st.dataframe(
            delinquency[
                ["scenario", "snapshot_date", "new_delinquencies", "cures", "relapses", "cure_rate"]
            ],
            width="stretch",
        )

    if not cure_summary.empty:
        st.subheader("Redefault (relapse) rate")
        if "n_ever_cured" in cure_summary.columns:
            grouped = cure_summary.groupby("scenario", as_index=False).agg(
                n_ever_cured=("n_ever_cured", "sum"), n_redefaulted=("n_redefaulted", "sum")
            )
        else:
            grouped = cure_summary.groupby("scenario", as_index=False).agg(
                n_ever_cured=("was_ever_cured", "sum"), n_redefaulted=("redefaulted", "sum")
            )
        grouped["redefault_rate"] = [
            safe_ratio(r, c)
            for r, c in zip(grouped["n_redefaulted"], grouped["n_ever_cured"], strict=True)
        ]
        st.dataframe(grouped, width="stretch")
        st.caption(
            "Time-to-cure is not computed in this build - it would require a dedicated "
            "day-count calculation not yet in the warehouse layer (documented limitation)."
        )

    if not collections.empty:
        st.subheader("Collections activity")
        st.dataframe(
            collections[
                [
                    "scenario",
                    "event_month",
                    "contact_events",
                    "contracts_contacted",
                    "contact_rate",
                    "promise_rate",
                ]
            ],
            width="stretch",
        )
        st.warning(
            "collections_change varies only AGGREGATE, scenario-level DGP parameters - there "
            "is no per-contact causal attribution in these results (not evidence a specific "
            "collections action caused a specific outcome)."
        )

    if not writeoff.empty:
        st.subheader("Write-off and recovery")
        totals = queries.totals_by_scenario(
            writeoff,
            [
                "write_off_count",
                "total_write_off_amount",
                "recovery_count",
                "total_recovery_amount",
            ],
        )
        if not totals.empty:
            totals["recovery_rate"] = [
                safe_ratio(r, w)
                for r, w in zip(
                    totals["total_recovery_amount"], totals["total_write_off_amount"], strict=True
                )
            ]
            st.dataframe(totals, width="stretch")
        if "avg_days_to_recovery" in writeoff.columns:
            avg_days = writeoff["avg_days_to_recovery"].dropna()
            if not avg_days.empty:
                st.metric("Avg. days between write-off and recovery", f"{avg_days.mean():.1f} days")

    render_provenance_caption(get_figure_provenance("cure_and_relapse"))
    methodology_link()


# --- 6. Scenario Lab ---------------------------------------------------


def render_scenario_lab(data: DashboardData, state: FilterState) -> None:
    st.header("Scenario Lab")
    _page_provenance_badge("scenario_lab")
    st.caption(
        "Baseline vs. counterfactual scenario comparison - a laboratory for reading DGP "
        "deltas, never an optimizer or a policy recommendation engine."
    )
    synthetic_warning_banner()

    scenario_cmp = _get(data, "scenario_comparison")
    macro_pp = _get(data, "macro_stress_pre_post")
    composition = data.composition

    if is_empty_result(scenario_cmp):
        empty_state("No scenario comparison rows available for this build.")
        return

    st.subheader("Baseline vs. scenario")
    st.dataframe(scenario_cmp, width="stretch")

    for scenario_name, comp in composition.items():
        st.markdown(f"**{scenario_name}: composition vs. performance**")
        st.caption(sample_badge(comp.get("shared_booked_count"), comp.get("sample_classification")))
        render_sample_warning(comp.get("shared_booked_count"), comp.get("sample_classification"))
        st.json(comp, expanded=False)

    if not macro_pp.empty:
        st.subheader("Macroeconomic stress: pre- vs. post-shock")
        st.dataframe(macro_pp, width="stretch")
        pre = macro_pp[macro_pp["period"] == "pre_shock"]
        if not pre.empty:
            pre_delta = float(pre["par90_delta_abs"].iloc[0])
            st.caption(
                f"Pre-shock PAR90 delta: {format_delta_abs(pre_delta, as_percent=True)} "
                "(expected ~0 by CRN design)."
            )

    st.subheader("Multi-seed robustness (variability across synthetic DGP runs)")
    robustness = load_robustness_report()
    if not robustness:
        st.info(
            "No multi-seed robustness report found at "
            "reports/synthetic_validation/multiseed_robustness.json - run "
            "`credlens.analysis.robustness.full_robustness_sweep` first."
        )
    else:
        for scenario_name, result in robustness.get("scenarios", {}).items():
            st.markdown(f"**{scenario_name}** ({result['n_seeds']} seeds)")
            metrics_with_direction = {
                name: m for name, m in result["metrics"].items() if m.get("expected_direction")
            }
            for metric_name, m in metrics_with_direction.items():
                st.write(
                    f"- `{metric_name}`: mean delta {m['mean']:+.4f}, stdev {m['stdev']:.4f}, "
                    f"{m['fraction_in_expected_direction']:.0%} of seeds in expected direction "
                    f"({m['inversions']} inversion(s))"
                )
            pre_shock = result.get("pre_shock_equality")
            if pre_shock:
                st.caption(
                    f"Pre-shock equality: {pre_shock['fraction_identical']:.0%} of seeds identical "
                    f"(max abs delta {pre_shock['max_absolute_delta']:.6f})."
                )
        st.caption(
            f"Label: {robustness.get('label_en', 'Variability across synthetic DGP runs')} - "
            "never a statistical confidence interval."
        )

    render_provenance_caption(get_figure_provenance("policy_scenario_comparison"))
    methodology_link()


# --- 7. Data Quality & Methodology ---------------------------------------------------


def render_data_quality_methodology(data: DashboardData) -> None:
    st.header("Data Quality & Methodology")
    _page_provenance_badge("data_quality_methodology")

    cols = st.columns(3)
    with cols[0]:
        st.metric("Mode", data.mode)
    with cols[1]:
        st.metric("Build ID", data.build_id)
    with cols[2]:
        st.metric("Fingerprint", data.fingerprint[:16] + "...")

    st.subheader("Source classification")
    from credlens.analysis.data_provenance import FIGURE_PROVENANCE, TABLE_PROVENANCE

    rows = [
        {"table": name, "category": record.category, "label": record.label("en")}
        for name, record in sorted(TABLE_PROVENANCE.items())
    ]
    st.dataframe(rows, width="stretch")

    st.subheader("Figures")
    figure_rows = [
        {"figure": name, "category": record.category}
        for name, record in sorted(FIGURE_PROVENANCE.items())
    ]
    st.dataframe(figure_rows, width="stretch")

    st.subheader("Documentation")
    st.markdown(
        "- [`docs/warehouse_architecture.md`](../docs/warehouse_architecture.md)\n"
        "- [`docs/analysis_architecture.md`](../docs/analysis_architecture.md)\n"
        "- [`docs/assumptions_and_limitations.md`](../docs/assumptions_and_limitations.md)\n"
        "- [`analysis/specifications/segmentation_policy.md`]"
        "(../analysis/specifications/segmentation_policy.md)\n"
    )

    st.subheader("Limitations")
    st.markdown(
        "- Every portfolio number is synthetic; no real-institution claim.\n"
        "- No revenue/cost/LGD/EAD/regulatory PD data exists in this project.\n"
        "- Scenario comparisons are only valid within the same suite_id.\n"
        "- `collections_change` is never causal evidence for an individual action.\n"
    )


# --- 8. Public Benchmarks ---------------------------------------------------


def render_public_benchmarks() -> None:
    st.header("Public Benchmarks")
    _page_provenance_badge("public_benchmarks")
    st.caption(
        "REAL public data (UCI, South German Credit, BCB SGS), kept completely separate "
        "from the synthetic portfolio above - never merged, never treated as a CredLens result."
    )

    from credlens.analysis.benchmark import profile_public_sources

    profiles = [p.to_dict() for p in profile_public_sources()]
    if not profiles:
        st.info(
            "No public benchmark sources found (data/raw/ is empty in this environment). "
            "This is an optional appendix - see docs/dataset_selection.md."
        )
        return

    st.plotly_chart(charts.public_benchmark_bar(profiles), width="stretch")
    for profile in profiles:
        with st.expander(profile["source_id"]):
            st.json(profile, expanded=False)
    st.caption(
        "Public benchmark data - separate from the synthetic portfolio / "
        "Public market context - Banco Central do Brasil."
    )
