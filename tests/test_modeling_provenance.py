"""Tests for credlens.modeling.provenance (Phase 8 section 27): the
Model Lab page's provenance record validates against Phase 7's own
public_benchmark taxonomy and is never mislabeled as synthetic."""

from __future__ import annotations

from credlens.modeling.provenance import (
    MODEL_LAB_PROVENANCE_LABEL_EN,
    NOT_SUITABLE_FOR_REAL_LENDING_EN,
    NOT_SUITABLE_FOR_REAL_LENDING_PT_BR,
    SEPARATION_NOTICE_EN,
    SEPARATION_NOTICE_PT_BR,
    modeling_provenance_record,
)


class TestModelingProvenanceRecord:
    def test_category_is_public_benchmark(self) -> None:
        record = modeling_provenance_record()
        assert record.category == "public_benchmark"
        assert record.source_ids == ("uci-default-credit",)

    def test_label_never_claims_synthetic(self) -> None:
        record = modeling_provenance_record()
        assert not record.label("en").lower().startswith("synthetic")
        assert not record.label("pt-BR").lower().startswith("sintetico")


def test_labels_are_never_empty() -> None:
    assert MODEL_LAB_PROVENANCE_LABEL_EN
    assert SEPARATION_NOTICE_EN
    assert SEPARATION_NOTICE_PT_BR
    assert NOT_SUITABLE_FOR_REAL_LENDING_EN
    assert NOT_SUITABLE_FOR_REAL_LENDING_PT_BR


def test_provenance_label_mentions_uci_and_taiwan() -> None:
    assert "UCI" in MODEL_LAB_PROVENANCE_LABEL_EN
    assert "2005" in MODEL_LAB_PROVENANCE_LABEL_EN
