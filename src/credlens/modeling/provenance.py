"""Provenance labeling for the Phase 8 modeling layer (section 27) -
plugs into Phase 7's existing taxonomy (`credlens.analysis.data_
provenance`) rather than declaring a new one. Every modeling artifact
(model card, technical report, Model Lab dashboard page, batch scoring
output) carries this SAME label - never a "synthetic" watermark, and
never silently unlabeled.
"""

from __future__ import annotations

from credlens.analysis.data_provenance import ProvenanceRecord, validate_provenance

MODEL_LAB_PROVENANCE_LABEL_EN = "Historical public benchmark - UCI, Taiwan, 2005"
MODEL_LAB_PROVENANCE_LABEL_PT_BR = "Benchmark público histórico - UCI, Taiwan, 2005"

SEPARATION_NOTICE_EN = (
    "This model was trained on a historical public benchmark and is not connected to the "
    "synthetic CredLens portfolio."
)
SEPARATION_NOTICE_PT_BR = (
    "Este modelo foi treinado em um benchmark público histórico e não está conectado ao "
    "portfólio sintético do CredLens."
)

NOT_SUITABLE_FOR_REAL_LENDING_EN = "Not suitable for real lending decisions."
NOT_SUITABLE_FOR_REAL_LENDING_PT_BR = "Não é adequado para decisões reais de concessão de crédito."


def modeling_provenance_record() -> ProvenanceRecord:
    """The single provenance record every modeling surface should cite -
    validated on every call so a future edit to the label text can never
    silently start claiming this is synthetic data."""
    record = ProvenanceRecord(category="public_benchmark", source_ids=("uci-default-credit",))
    validate_provenance(record)
    return record
