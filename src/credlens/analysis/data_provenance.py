"""Data-provenance classification (Phase 7 gate C).

Not every source in this project is synthetic: `credlens.analysis.charts`
watermarked *every* figure "Synthetic data", including
`public_benchmark_overview` - which plots REAL UCI/South German Credit/BCB
SGS data. That mislabeling is exactly the risk this module closes.

Every table, figure, dashboard page, and export must declare one of five
categories, never assumed by default:

  - `synthetic_operational`: the baseline synthetic portfolio (CredLens's
    own DGP, no counterfactual scenario applied).
  - `synthetic_scenario`: a synthetic counterfactual scenario
    (policy_expansion/tightening, macroeconomic_stress,
    collections_change) compared against baseline.
  - `public_benchmark`: a real, licensed public credit dataset used purely
    as an external benchmark (UCI Default of Credit Card Clients, South
    German Credit) - never merged with the synthetic portfolio.
  - `public_market_context`: a real Banco Central do Brasil (BCB SGS)
    macro time series - contextual, not a labeled credit benchmark.
  - `mixed_context`: an aggregate that deliberately and visibly combines
    sources from more than one category above - only permitted with a
    non-empty `note` explaining the combination and >= 2 declared
    `source_ids`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ProvenanceCategory = Literal[
    "synthetic_operational",
    "synthetic_scenario",
    "public_benchmark",
    "public_market_context",
    "mixed_context",
]

# Exact label text (Phase 7 gate C section 6.1).
LABELS_EN: dict[ProvenanceCategory, str] = {
    "synthetic_operational": "Synthetic data - illustrative portfolio",
    "synthetic_scenario": "Synthetic data - illustrative portfolio (counterfactual scenario)",
    "public_benchmark": "Public benchmark data - separate from the synthetic portfolio",
    "public_market_context": "Public market context - Banco Central do Brasil",
    "mixed_context": "Mixed sources - see methodological note",
}
LABELS_PT: dict[ProvenanceCategory, str] = {
    "synthetic_operational": "Dados sinteticos - carteira ilustrativa",
    "synthetic_scenario": "Dados sinteticos - carteira ilustrativa (cenario contrafactual)",
    "public_benchmark": "Dados de benchmark publico - separados da carteira sintetica",
    "public_market_context": "Contexto de mercado publico - Banco Central do Brasil",
    "mixed_context": "Fontes mistas - ver nota metodologica",
}

# The literal watermark historically stamped on every figure
# (credlens.analysis.charts._watermark's default) - kept as a named
# constant so callers pass the SAME string credlens.analysis.charts
# already uses, instead of a second hand-typed copy.
SYNTHETIC_WATERMARK_EN = "Synthetic data - CredLens DGP, not a real institution"


class ProvenanceError(Exception):
    """Raised when a provenance record violates Phase 7 gate C's rules."""


@dataclass(frozen=True)
class ProvenanceRecord:
    category: ProvenanceCategory
    source_ids: tuple[str, ...]
    note: str | None = None

    def label(self, lang: str = "en") -> str:
        labels = LABELS_PT if lang == "pt-BR" else LABELS_EN
        base = labels[self.category]
        if self.category == "mixed_context" and self.note:
            return f"{base}: {self.note}"
        return base

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "source_ids": list(self.source_ids),
            "note": self.note,
            "label_en": self.label("en"),
            "label_pt_br": self.label("pt-BR"),
        }


def validate_provenance(record: ProvenanceRecord) -> None:
    """Raises ProvenanceError for exactly the failure modes Phase 7 gate C
    section 6.2 requires tests for."""
    label_en = record.label("en")
    # The public_benchmark label legitimately CONTRASTS itself with the
    # synthetic portfolio ("...separate from the synthetic portfolio") -
    # the forbidden pattern is the data being CLAIMED as synthetic
    # ("Synthetic data ..."), not the bare word appearing at all.
    if record.category in ("public_benchmark", "public_market_context") and (
        label_en.lower().startswith("synthetic")
    ):
        raise ProvenanceError(
            f"A {record.category!r} record must never be labeled as synthetic data: {label_en!r}."
        )
    if record.category in ("synthetic_operational", "synthetic_scenario") and not (
        label_en.lower().startswith("synthetic")
    ):
        raise ProvenanceError(
            f"A {record.category!r} record must carry an explicit 'Synthetic data' label."
        )
    if record.category == "public_market_context" and not record.source_ids:
        raise ProvenanceError(
            "public_market_context requires at least one source_id "
            "(e.g. a BCB SGS series code such as 'bcb-sgs-20570')."
        )
    if record.category == "mixed_context":
        if len(record.source_ids) < 2:
            raise ProvenanceError(
                "mixed_context requires at least two declared source_ids "
                "(one per combined category)."
            )
        if not record.note:
            raise ProvenanceError(
                "mixed_context requires a non-empty methodological note explaining the "
                "combination and why the sources are not directly comparable."
            )


# --- Known public source -> category mapping --------------------------------
# Every acquired public source (Phase 2, docs/data_licensing.md) must be
# registered here explicitly - an unregistered source_id is refused
# rather than silently defaulted, so a newly-added source can never slip
# through unlabeled.
_SOURCE_ID_CATEGORY: dict[str, ProvenanceCategory] = {
    "uci-default-credit": "public_benchmark",
    "south-german-credit": "public_benchmark",
    "bcb-sgs-20570": "public_market_context",
    "bcb-sgs-21112": "public_market_context",
}


def classify_source_id(source_id: str) -> ProvenanceCategory:
    """Classifies one of the project's registered public source_ids.
    Raises ProvenanceError for anything not explicitly registered -
    Phase 7 gate C's "every source must know its provenance" is
    enforced here as a hard refusal, not a silent guess."""
    try:
        return _SOURCE_ID_CATEGORY[source_id]
    except KeyError as exc:
        raise ProvenanceError(
            f"source_id {source_id!r} is not a registered public source - see "
            "credlens.analysis.data_provenance._SOURCE_ID_CATEGORY. Register it explicitly "
            "before using it in a report/dashboard, do not assume its provenance."
        ) from exc


def provenance_for_source(source_id: str) -> ProvenanceRecord:
    return ProvenanceRecord(category=classify_source_id(source_id), source_ids=(source_id,))


# --- Registry: every figure/table this project currently produces ----------
# Phase 7 gate C: "Cada tabela, figura, pagina e exportacao deve conhecer
# sua proveniencia." Registered once, here, so credlens.analysis.charts,
# credlens.analysis.reporting, and the dashboard never have to re-decide
# a chart/table's category themselves.
FIGURE_PROVENANCE: dict[str, ProvenanceRecord] = {
    "credit_funnel": ProvenanceRecord("synthetic_scenario", ()),
    "outstanding_balance_over_time": ProvenanceRecord("synthetic_scenario", ()),
    "par_curves": ProvenanceRecord("synthetic_operational", ()),
    "roll_rate_heatmap": ProvenanceRecord("synthetic_operational", ()),
    "vintage_curves": ProvenanceRecord("synthetic_operational", ()),
    "cure_and_relapse": ProvenanceRecord("synthetic_scenario", ()),
    "writeoff_and_recovery": ProvenanceRecord("synthetic_scenario", ()),
    "policy_scenario_comparison": ProvenanceRecord("synthetic_scenario", ()),
    "macro_stress_pre_post": ProvenanceRecord("synthetic_scenario", ()),
    "multiseed_stability": ProvenanceRecord("synthetic_scenario", ()),
    "quality_provenance_scorecard": ProvenanceRecord("synthetic_operational", ()),
    "public_benchmark_overview": ProvenanceRecord(
        "mixed_context",
        ("uci-default-credit", "south-german-credit", "bcb-sgs-20570", "bcb-sgs-21112"),
        note=(
            "Combines public_benchmark row counts (UCI/South German Credit) with "
            "public_market_context observation counts (BCB SGS monthly series) on one "
            "bar chart for compactness only - the two are different units of count and "
            "are not directly comparable; see docs/data_licensing.md."
        ),
    ),
}

TABLE_PROVENANCE: dict[str, ProvenanceRecord] = {
    "funnel_monthly": ProvenanceRecord("synthetic_scenario", ()),
    "portfolio_monthly": ProvenanceRecord("synthetic_scenario", ()),
    "delinquency_monthly": ProvenanceRecord("synthetic_scenario", ()),
    "vintage_cohorts": ProvenanceRecord("synthetic_scenario", ()),
    "roll_rates": ProvenanceRecord("synthetic_scenario", ()),
    "cure_and_redefault": ProvenanceRecord("synthetic_scenario", ()),
    "collections_performance": ProvenanceRecord("synthetic_scenario", ()),
    "writeoff_recovery": ProvenanceRecord("synthetic_scenario", ()),
    "scenario_comparison": ProvenanceRecord("synthetic_scenario", ()),
    "macro_stress_pre_post": ProvenanceRecord("synthetic_scenario", ()),
    "funnel_by_channel_and_scenario": ProvenanceRecord("synthetic_scenario", ()),
    "portfolio_by_region_and_channel": ProvenanceRecord("synthetic_scenario", ()),
    "policy_version_comparison": ProvenanceRecord("synthetic_scenario", ()),
    "credit_risk_segment_summary": ProvenanceRecord("synthetic_scenario", ()),
}


def get_figure_provenance(name: str) -> ProvenanceRecord:
    try:
        return FIGURE_PROVENANCE[name]
    except KeyError as exc:
        raise ProvenanceError(
            f"Figure {name!r} has no registered provenance - register it in "
            "credlens.analysis.data_provenance.FIGURE_PROVENANCE before generating it."
        ) from exc


def get_table_provenance(name: str) -> ProvenanceRecord:
    try:
        return TABLE_PROVENANCE[name]
    except KeyError as exc:
        raise ProvenanceError(
            f"Table {name!r} has no registered provenance - register it in "
            "credlens.analysis.data_provenance.TABLE_PROVENANCE before generating it."
        ) from exc
