"""CredLens Streamlit dashboard support package (Phase 7).

A PRESENTATION layer only: every function here reads already-validated
marts/reports and formats/filters/exports them. No business rule is
computed here - KPI logic lives in `credlens.analysis`/`warehouse/models/
marts/*.sql`, sample-size policy in `credlens.analysis.sample_policy`,
provenance labeling in `credlens.analysis.data_provenance`. The Streamlit
scripts themselves live under the top-level `dashboard/` directory (not
inside the installable package) and import from here.
"""

from __future__ import annotations
