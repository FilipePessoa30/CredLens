"""Provenance labels for the Phase 9 independent-validation layer - reuses
Phase 8's `credlens.modeling.provenance` labels rather than declaring a
new taxonomy; adds the "independent of training-time evidence" framing
this package is specifically about.
"""

from __future__ import annotations

from credlens.modeling.provenance import (
    MODEL_LAB_PROVENANCE_LABEL_EN,
    MODEL_LAB_PROVENANCE_LABEL_PT_BR,
    NOT_SUITABLE_FOR_REAL_LENDING_EN,
    NOT_SUITABLE_FOR_REAL_LENDING_PT_BR,
    SEPARATION_NOTICE_EN,
    SEPARATION_NOTICE_PT_BR,
)

INDEPENDENT_VALIDATION_LABEL_EN = (
    "Independent validation - recomputed from frozen evidence, not copied from the Phase 8 report"
)
INDEPENDENT_VALIDATION_LABEL_PT_BR = (
    "Validação independente - recomputada a partir de evidência congelada, não copiada do "
    "relatório da Fase 8"
)

__all__ = [
    "INDEPENDENT_VALIDATION_LABEL_EN",
    "INDEPENDENT_VALIDATION_LABEL_PT_BR",
    "MODEL_LAB_PROVENANCE_LABEL_EN",
    "MODEL_LAB_PROVENANCE_LABEL_PT_BR",
    "NOT_SUITABLE_FOR_REAL_LENDING_EN",
    "NOT_SUITABLE_FOR_REAL_LENDING_PT_BR",
    "SEPARATION_NOTICE_EN",
    "SEPARATION_NOTICE_PT_BR",
]
