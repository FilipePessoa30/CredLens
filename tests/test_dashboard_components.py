"""Direct unit tests for credlens.dashboard.components (Phase 7 sections
11, 13) - every branch (None/insufficient/limited/adequate sample states,
empty insight lists) rather than only whatever a real build's own data
happens to exercise via AppTest."""

from __future__ import annotations

from credlens.analysis.data_provenance import ProvenanceRecord
from credlens.dashboard.components import (
    empty_state,
    kpi_card,
    mode_badge,
    render_insight_summary,
    render_provenance_caption,
    render_sample_warning,
    sample_badge,
)


class TestSampleBadge:
    def test_none_values_produce_empty_string(self) -> None:
        assert sample_badge(None, None) == ""
        assert sample_badge(10, None) == ""
        assert sample_badge(None, "adequate") == ""

    def test_insufficient_badge(self) -> None:
        assert "insufficient" in sample_badge(5, "insufficient")

    def test_limited_badge(self) -> None:
        assert "limited" in sample_badge(50, "limited")

    def test_adequate_badge(self) -> None:
        assert "adequate" in sample_badge(500, "adequate")


class TestRenderSampleWarning:
    def test_none_values_do_not_raise(self) -> None:
        render_sample_warning(None, None)
        render_sample_warning(10, None)
        render_sample_warning(None, "adequate")

    def test_insufficient_does_not_raise(self) -> None:
        render_sample_warning(5, "insufficient")

    def test_limited_does_not_raise(self) -> None:
        render_sample_warning(50, "limited")

    def test_adequate_does_not_raise(self) -> None:
        render_sample_warning(500, "adequate")


class TestRenderProvenanceCaption:
    def test_does_not_raise(self) -> None:
        record = ProvenanceRecord(category="synthetic_operational", source_ids=())
        render_provenance_caption(record)
        render_provenance_caption(record, lang="pt-BR")


class TestKpiCard:
    def test_minimal_call_does_not_raise(self) -> None:
        kpi_card("Label", "123")

    def test_with_delta_and_help_does_not_raise(self) -> None:
        kpi_card("Label", "123", delta="+5", delta_color="inverse", help_text="tooltip")


class TestEmptyState:
    def test_does_not_raise(self) -> None:
        empty_state("Try widening the filters.")


class TestModeBadge:
    def test_warehouse_mode_does_not_raise(self) -> None:
        mode_badge("warehouse", "a" * 64)

    def test_demo_mode_does_not_raise(self) -> None:
        mode_badge("demo", "b" * 64)


class TestRenderInsightSummary:
    def test_empty_list_does_not_raise(self) -> None:
        render_insight_summary([])

    def test_only_unsupported_insights_produces_no_ready_items(self) -> None:
        insights = [{"statement_type": "unsupported", "title": "x"}]
        render_insight_summary(insights)

    def test_a_ready_insight_is_rendered(self) -> None:
        insights = [
            {
                "statement_type": "observed_synthetic_result",
                "sample_classification": "adequate",
                "statement": {"en": "Something happened."},
                "title": "t",
            }
        ]
        render_insight_summary(insights)

    def test_max_items_is_respected(self) -> None:
        insights = [
            {
                "statement_type": "observed_synthetic_result",
                "sample_classification": "adequate",
                "statement": {"en": f"Insight {i}"},
                "title": f"t{i}",
            }
            for i in range(10)
        ]
        render_insight_summary(insights, max_items=2)
