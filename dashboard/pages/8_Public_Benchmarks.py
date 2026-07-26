"""Public Benchmarks page - thin entrypoint, see
`credlens.dashboard.pages.render_public_benchmarks` for the composition logic.
Visually and structurally separate from every synthetic-portfolio page -
does not even need `credlens_data` (it reads public sources directly)."""

from __future__ import annotations

import streamlit as st

from credlens.dashboard.pages import render_public_benchmarks

if "credlens_data" in st.session_state:
    from credlens.dashboard.components import mode_badge

    _data = st.session_state["credlens_data"]
    mode_badge(_data.mode, _data.fingerprint)

render_public_benchmarks()
