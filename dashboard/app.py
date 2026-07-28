"""CredLens Decision Intelligence Dashboard - entry point (Phase 7).

Launched by `credlens dashboard run --build-id <BUILD_ID>` or
`credlens dashboard run --demo` (which run `streamlit run dashboard/app.py
-- --build-id <BUILD_ID>` / `-- --demo` under the hood). This script is
only the NAVIGATION router - it resolves/validates the data source once,
then hands off to one of the 8 page scripts under `dashboard/pages/`. All
actual business logic lives in `credlens.dashboard`/`credlens.analysis`,
never here.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from credlens.dashboard.bootstrap import BootstrapError, load_validated_dashboard_data

st.set_page_config(
    page_title="CredLens - Decision Intelligence Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

try:
    config, data = load_validated_dashboard_data()
except BootstrapError as exc:
    st.error(f"Could not start the dashboard: {exc}")
    st.stop()

st.session_state["credlens_config"] = config
st.session_state["credlens_data"] = data

_PAGES_DIR = Path(__file__).parent / "pages"

pages = [
    st.Page(str(_PAGES_DIR / "1_Executive_Overview.py"), title="Executive Overview", icon="📊"),
    st.Page(str(_PAGES_DIR / "2_Credit_Funnel.py"), title="Credit Funnel", icon="🔻"),
    st.Page(
        str(_PAGES_DIR / "3_Portfolio_Delinquency.py"),
        title="Portfolio & Delinquency",
        icon="💼",
    ),
    st.Page(str(_PAGES_DIR / "4_Vintages_Roll_Rates.py"), title="Vintages & Roll Rates", icon="📈"),
    st.Page(
        str(_PAGES_DIR / "5_Cure_Collections_Recovery.py"),
        title="Cure, Collections & Recovery",
        icon="🔄",
    ),
    st.Page(str(_PAGES_DIR / "6_Scenario_Lab.py"), title="Scenario Lab", icon="🧪"),
    st.Page(
        str(_PAGES_DIR / "7_Data_Quality_Methodology.py"),
        title="Data Quality & Methodology",
        icon="🛡️",
    ),
    st.Page(str(_PAGES_DIR / "8_Public_Benchmarks.py"), title="Public Benchmarks", icon="🌐"),
    st.Page(str(_PAGES_DIR / "9_Model_Lab.py"), title="Model Lab", icon="🔬"),
    st.Page(
        str(_PAGES_DIR / "10_Model_Monitoring_Lab.py"), title="Model Monitoring Lab", icon="📡"
    ),
]

navigation = st.navigation(pages)
navigation.run()
