"""Tests for credlens.dashboard.provenance (Phase 7 gate C): every
required dashboard page has a declared provenance category, and an
unknown page key falls back to a safe default rather than raising."""

from __future__ import annotations

from credlens.dashboard.provenance import PAGE_PROVENANCE, page_provenance_category


class TestPageProvenance:
    def test_every_required_page_is_registered(self) -> None:
        for page_key in (
            "executive_overview",
            "credit_funnel",
            "portfolio_delinquency",
            "vintages_roll_rates",
            "cure_collections_recovery",
            "scenario_lab",
            "data_quality_methodology",
            "public_benchmarks",
        ):
            assert page_key in PAGE_PROVENANCE

    def test_public_benchmarks_page_is_mixed_context(self) -> None:
        assert page_provenance_category("public_benchmarks") == "mixed_context"

    def test_data_quality_page_is_synthetic_operational(self) -> None:
        assert page_provenance_category("data_quality_methodology") == "synthetic_operational"

    def test_unknown_page_falls_back_to_a_safe_default(self) -> None:
        assert page_provenance_category("no_such_page") == "synthetic_operational"
