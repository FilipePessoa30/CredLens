"""Vintages & Roll Rates page - thin entrypoint, see
`credlens.dashboard.pages.render_vintages_roll_rates` for the composition logic."""

from __future__ import annotations

import streamlit as st

from credlens.dashboard.bootstrap import BootstrapError, load_validated_dashboard_data
from credlens.dashboard.pages import render_vintages_roll_rates
from credlens.dashboard.sidebar import render_sidebar

if "credlens_data" not in st.session_state:
    try:
        config, data = load_validated_dashboard_data()
    except BootstrapError as exc:
        st.error(f"Could not load dashboard data: {exc}")
        st.stop()
    st.session_state["credlens_config"] = config
    st.session_state["credlens_data"] = data

state = render_sidebar(st.session_state["credlens_data"])
render_vintages_roll_rates(st.session_state["credlens_data"], state)
