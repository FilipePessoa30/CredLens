"""Data Quality & Methodology page - thin entrypoint, see
`credlens.dashboard.pages.render_data_quality_methodology` for the composition logic."""

from __future__ import annotations

import streamlit as st

from credlens.dashboard.bootstrap import BootstrapError, load_validated_dashboard_data
from credlens.dashboard.components import mode_badge
from credlens.dashboard.pages import render_data_quality_methodology

if "credlens_data" not in st.session_state:
    try:
        config, data = load_validated_dashboard_data()
    except BootstrapError as exc:
        st.error(f"Could not load dashboard data: {exc}")
        st.stop()
    st.session_state["credlens_config"] = config
    st.session_state["credlens_data"] = data

_data = st.session_state["credlens_data"]
mode_badge(_data.mode, _data.fingerprint)
render_data_quality_methodology(_data)
