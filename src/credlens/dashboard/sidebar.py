"""Shared sidebar: mode badge + every filter widget, using consistent
`st.session_state` keys so selections persist across page navigation
(Phase 7 section 12: "filtros devem preservar contexto entre paginas
quando possivel"). Every page script calls `render_sidebar` once.
"""

from __future__ import annotations

import streamlit as st

from credlens.dashboard.components import mode_badge
from credlens.dashboard.data_access import DashboardData
from credlens.dashboard.filters import FilterOptions, FilterState, derive_filter_options

_KEY_PREFIX = "credlens_filter_"


def _multiselect(label: str, options: list[str], key_suffix: str) -> list[str]:
    if not options:
        return []
    return st.sidebar.multiselect(label, options=options, key=f"{_KEY_PREFIX}{key_suffix}")


def render_sidebar(data: DashboardData) -> FilterState:
    mode_badge(data.mode, data.fingerprint)
    st.sidebar.divider()
    st.sidebar.subheader("Filters")

    options: FilterOptions = derive_filter_options(data)

    scenarios = _multiselect("Scenario", options.scenarios, "scenarios")
    channels = _multiselect("Channel", options.channels, "channels")
    products = _multiselect("Product", options.products, "products")
    regions = _multiselect("Region", options.regions, "regions")
    policy_versions = _multiselect("Policy version", options.policy_versions, "policy_versions")
    bureau_buckets = _multiselect(
        "Bureau score bucket", options.bureau_score_buckets, "bureau_score_buckets"
    )
    income_bands = _multiselect("Income band", options.income_bands, "income_bands")
    contract_value_bands = _multiselect(
        "Contract value band", options.contract_value_bands, "contract_value_bands"
    )
    vintage_months = _multiselect(
        "Cohort (vintage month)", options.vintage_months, "vintage_months"
    )
    dpd_buckets = _multiselect("DPD bucket", options.dpd_buckets, "dpd_buckets")

    date_range: tuple[str, str] | None = None
    if options.date_min and options.date_max and options.date_min != options.date_max:
        import datetime as dt

        picked = st.sidebar.slider(
            "Date range",
            min_value=dt.date.fromisoformat(options.date_min),
            max_value=dt.date.fromisoformat(options.date_max),
            value=(
                dt.date.fromisoformat(options.date_min),
                dt.date.fromisoformat(options.date_max),
            ),
            key=f"{_KEY_PREFIX}date_range",
        )
        date_range = (str(picked[0]), str(picked[1]))

    return FilterState(
        scenarios=scenarios,
        channels=channels,
        products=products,
        regions=regions,
        policy_versions=policy_versions,
        bureau_score_buckets=bureau_buckets,
        income_bands=income_bands,
        contract_value_bands=contract_value_bands,
        vintage_months=vintage_months,
        dpd_buckets=dpd_buckets,
        date_range=date_range,
    )
