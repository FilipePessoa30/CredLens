"""Page-level provenance declarations (Phase 7 gate C, section 6).

Every dashboard page declares its OWN provenance category up front -
never inherited implicitly. Table/figure-level records still come from
`credlens.analysis.data_provenance` (the single registry); this module
only adds the one thing that registry does not cover: which category a
whole PAGE belongs to, for the page header badge.
"""

from __future__ import annotations

from credlens.analysis.data_provenance import ProvenanceCategory

PAGE_PROVENANCE: dict[str, ProvenanceCategory] = {
    "executive_overview": "synthetic_scenario",
    "credit_funnel": "synthetic_scenario",
    "portfolio_delinquency": "synthetic_scenario",
    "vintages_roll_rates": "synthetic_scenario",
    "cure_collections_recovery": "synthetic_scenario",
    "scenario_lab": "synthetic_scenario",
    "data_quality_methodology": "synthetic_operational",
    "public_benchmarks": "mixed_context",
    "model_lab": "public_benchmark",
    "model_monitoring_lab": "public_benchmark",
}


def page_provenance_category(page_key: str) -> ProvenanceCategory:
    return PAGE_PROVENANCE.get(page_key, "synthetic_operational")
