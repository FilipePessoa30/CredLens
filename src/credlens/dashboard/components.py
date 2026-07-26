"""Reusable Streamlit UI building blocks (Phase 7 sections 11, 13).

Every component here reads pre-computed values (never recomputes a KPI)
and applies the sample-size policy (`credlens.analysis.sample_policy`)
and provenance labeling (`credlens.analysis.data_provenance`) so pages
never have to re-derive that logic themselves. Colour is never the only
signal - every "at risk"/"insufficient sample" state also carries a text
label/icon.
"""

from __future__ import annotations

from typing import Any, Literal

import streamlit as st

from credlens.analysis.data_provenance import ProvenanceRecord
from credlens.analysis.sample_policy import CLASSIFICATION_LABELS, SampleClassification

# A sober, financial-services-appropriate palette (Phase 7 section 13) -
# consistent scenario colours across every page/chart.
SCENARIO_COLORS: dict[str, str] = {
    "baseline": "#1f5fa8",  # blue
    "policy_expansion": "#6a3d9a",  # purple
    "policy_tightening": "#e6842e",  # orange
    "macroeconomic_stress": "#8b1a1a",  # dark red
    "collections_change": "#0e7c7b",  # teal
}
BENCHMARK_COLOR = "#6b7280"  # gray - public benchmark data

_CLASSIFICATION_ICON: dict[SampleClassification, str] = {
    "insufficient": "⚠",
    "limited": "△",
    "adequate": "✓",
}


def sample_badge(n: int | None, classification: SampleClassification | None) -> str:
    """A short, colour-independent text badge for a sample size -
    e.g. '⚠ n=7 insufficient'. Never colour-only (Phase 7 section 11.2:
    "Nao use vermelho/verde como unica forma de comunicacao")."""
    if n is None or classification is None:
        return ""
    icon = _CLASSIFICATION_ICON.get(classification, "")
    return f"{icon} n={n:,} ({classification})"


def render_sample_warning(n: int | None, classification: SampleClassification | None) -> None:
    if classification is None or n is None:
        return
    if classification == "insufficient":
        st.warning(
            f"Insufficient sample (n={n:,}) - {CLASSIFICATION_LABELS['insufficient']}. "
            "Shown for audit only; not ranked or recommended."
        )
    elif classification == "limited":
        st.caption(f"△ Limited sample (n={n:,}) - {CLASSIFICATION_LABELS['limited']}.")


def render_provenance_caption(record: ProvenanceRecord, lang: str = "en") -> None:
    st.caption(f"Data source: {record.label(lang)}")


def kpi_card(
    label: str,
    value: str,
    *,
    delta: str | None = None,
    delta_color: Literal["normal", "inverse", "off"] = "normal",
    help_text: str | None = None,
) -> None:
    """A single KPI card with unit-formatted value and an OPTIONAL
    baseline-comparison delta - `delta_color='normal'` lets Streamlit's
    own icon convey direction while the text itself always states the
    signed number (never colour-only)."""
    st.metric(label=label, value=value, delta=delta, delta_color=delta_color, help=help_text)


def empty_state(message: str) -> None:
    """A friendly empty state (Phase 7 section 12: "selecao vazia deve
    produzir estado vazio, nao erro") - never a stack trace, never a
    blank page."""
    st.info(f"No data matches the current filters. {message}")


def mode_badge(mode: str, fingerprint: str) -> None:
    """Renders which data mode is active - MUST always be visible
    (Phase 7 section 18.3: "o modo ativo deve aparecer claramente")."""
    label = "Validated warehouse" if mode == "warehouse" else "Demo aggregate package"
    st.sidebar.markdown(f"**Mode:** {label}")
    st.sidebar.caption(f"Fingerprint: `{fingerprint[:16]}...`")


def synthetic_warning_banner() -> None:
    st.warning(
        "All portfolio figures on this page are synthetic - illustrative data from CredLens's "
        "own data-generation process, not a real financial institution. See Data Quality & "
        "Methodology for full provenance."
    )


def methodology_link() -> None:
    st.caption(
        "Methodology: docs/analysis_architecture.md, docs/warehouse_architecture.md, "
        "docs/assumptions_and_limitations.md."
    )


_NOT_EXECUTIVE_READY_TYPES = frozenset({"unsupported", "hypothesis"})


def _is_dict_insight_executive_ready(insight: dict[str, Any]) -> bool:
    """Same rule as `credlens.analysis.insights.is_executive_ready`,
    applied to a plain dict (as read back from insights.yml) rather than
    an `Insight` dataclass instance."""
    if insight.get("statement_type") in _NOT_EXECUTIVE_READY_TYPES:
        return False
    return insight.get("sample_classification") != "insufficient"


def render_insight_summary(insights: list[dict[str, Any]], max_items: int = 5) -> None:
    """Summarizes validated, executive-ready insights (Phase 7 gate D) -
    never surfaces an `unsupported`/`hypothesis` statement or an
    `insufficient`-sample one here."""
    ready = [i for i in insights if _is_dict_insight_executive_ready(i)]
    if not ready:
        st.caption("No validated insights available for this build yet.")
        return
    for insight in ready[:max_items]:
        statement = insight.get("statement", {})
        st.markdown(f"- {statement.get('en', insight.get('title', ''))}")
