"""Tests for credlens.analysis.data_provenance (Phase 7 gate C): the
provenance classification that stops a public-benchmark figure from ever
being watermarked "Synthetic data" (a real bug this phase found in
credlens.analysis.charts.public_benchmark_overview - every chart used
`_save`'s hardcoded synthetic watermark unconditionally), and the five
explicit failure modes gate C section 6.2 requires tests for."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import ClassVar

import pytest
from PIL import Image

import credlens.analysis.data_provenance as prov_mod
from credlens.analysis import charts
from credlens.analysis.data_provenance import (
    FIGURE_PROVENANCE,
    TABLE_PROVENANCE,
    ProvenanceError,
    ProvenanceRecord,
    classify_source_id,
    get_figure_provenance,
    get_table_provenance,
    provenance_for_source,
    validate_provenance,
)


class TestLabelsNeverCrossCategories:
    def test_synthetic_labels_say_synthetic(self) -> None:
        for category in ("synthetic_operational", "synthetic_scenario"):
            record = ProvenanceRecord(category=category, source_ids=())
            assert "synthetic" in record.label("en").lower()

    def test_public_labels_are_never_claimed_as_synthetic_data(self) -> None:
        # public_benchmark legitimately CONTRASTS itself with the
        # synthetic portfolio ("...separate from the synthetic
        # portfolio") - the forbidden pattern is the label CLAIMING the
        # data itself is synthetic ("Synthetic data ..."), which
        # validate_provenance (tested below) actually enforces.
        for category in ("public_benchmark", "public_market_context"):
            record = ProvenanceRecord(category=category, source_ids=("bcb-sgs-20570",))
            assert not record.label("en").lower().startswith("synthetic")
            assert not record.label("pt-BR").lower().startswith("sintetico")
            validate_provenance(record)


class TestValidateProvenanceRejectsTheFiveRequiredFailureModes:
    """Phase 7 gate C section 6.2: tests must fail if..."""

    def test_public_benchmark_marked_synthetic_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(prov_mod.LABELS_EN, "public_benchmark", "Synthetic data (mislabeled)")
        with pytest.raises(ProvenanceError):
            validate_provenance(
                ProvenanceRecord(category="public_benchmark", source_ids=("uci-default-credit",))
            )

    def test_bcb_source_marked_synthetic_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(
            prov_mod.LABELS_EN, "public_market_context", "Synthetic data (mislabeled)"
        )
        with pytest.raises(ProvenanceError):
            validate_provenance(
                ProvenanceRecord(category="public_market_context", source_ids=("bcb-sgs-20570",))
            )

    def test_synthetic_figure_without_synthetic_label_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(prov_mod.LABELS_EN, "synthetic_operational", "Illustrative portfolio")
        with pytest.raises(ProvenanceError):
            validate_provenance(ProvenanceRecord(category="synthetic_operational", source_ids=()))

    def test_bcb_source_without_source_id_is_rejected(self) -> None:
        with pytest.raises(ProvenanceError):
            validate_provenance(ProvenanceRecord(category="public_market_context", source_ids=()))

    def test_mixed_context_without_two_declared_sources_is_rejected(self) -> None:
        with pytest.raises(ProvenanceError):
            validate_provenance(
                ProvenanceRecord(
                    category="mixed_context", source_ids=("uci-default-credit",), note="a note"
                )
            )

    def test_mixed_context_without_methodological_note_is_rejected(self) -> None:
        with pytest.raises(ProvenanceError):
            validate_provenance(
                ProvenanceRecord(
                    category="mixed_context",
                    source_ids=("uci-default-credit", "bcb-sgs-20570"),
                    note=None,
                )
            )

    def test_valid_mixed_context_passes(self) -> None:
        validate_provenance(
            ProvenanceRecord(
                category="mixed_context",
                source_ids=("uci-default-credit", "bcb-sgs-20570"),
                note="Combines a benchmark dataset with a macro series - not directly comparable.",
            )
        )

    def test_valid_bcb_record_passes(self) -> None:
        validate_provenance(
            ProvenanceRecord(category="public_market_context", source_ids=("bcb-sgs-20570",))
        )

    def test_valid_synthetic_record_passes(self) -> None:
        validate_provenance(ProvenanceRecord(category="synthetic_operational", source_ids=()))
        validate_provenance(ProvenanceRecord(category="synthetic_scenario", source_ids=()))


class TestProvenanceRecordToDict:
    def test_round_trips_every_field(self) -> None:
        record = ProvenanceRecord(
            category="mixed_context",
            source_ids=("uci-default-credit", "bcb-sgs-20570"),
            note="a note",
        )
        d = record.to_dict()
        assert d["category"] == "mixed_context"
        assert d["source_ids"] == ["uci-default-credit", "bcb-sgs-20570"]
        assert d["note"] == "a note"
        assert str(d["label_en"]).startswith("Mixed sources")
        assert "label_pt_br" in d


class TestClassifySourceId:
    def test_uci_and_south_german_are_public_benchmark(self) -> None:
        assert classify_source_id("uci-default-credit") == "public_benchmark"
        assert classify_source_id("south-german-credit") == "public_benchmark"

    def test_bcb_series_are_public_market_context(self) -> None:
        assert classify_source_id("bcb-sgs-20570") == "public_market_context"
        assert classify_source_id("bcb-sgs-21112") == "public_market_context"

    def test_unregistered_source_id_is_refused_not_guessed(self) -> None:
        with pytest.raises(ProvenanceError):
            classify_source_id("some-new-dataset-nobody-registered")

    def test_provenance_for_source_round_trips(self) -> None:
        record = provenance_for_source("bcb-sgs-20570")
        assert record.category == "public_market_context"
        assert record.source_ids == ("bcb-sgs-20570",)


class TestRegistryCompleteness:
    """Every figure/table credlens.analysis.runner actually produces must
    have a registered provenance record - a coherence check so a newly
    added chart/table can never ship unlabeled."""

    _RUNNER_FIGURE_NAMES: ClassVar[set[str]] = {
        "credit_funnel",
        "outstanding_balance_over_time",
        "par_curves",
        "roll_rate_heatmap",
        "vintage_curves",
        "cure_and_relapse",
        "writeoff_and_recovery",
        "policy_scenario_comparison",
        "macro_stress_pre_post",
        "multiseed_stability",
        "quality_provenance_scorecard",
        "public_benchmark_overview",
    }
    _RUNNER_TABLE_NAMES: ClassVar[set[str]] = {
        "funnel_monthly",
        "portfolio_monthly",
        "delinquency_monthly",
        "vintage_cohorts",
        "roll_rates",
        "cure_and_redefault",
        "collections_performance",
        "writeoff_recovery",
        "scenario_comparison",
        "macro_stress_pre_post",
        "funnel_by_channel_and_scenario",
        "portfolio_by_region_and_channel",
        "policy_version_comparison",
    }

    def test_every_runner_figure_is_registered(self) -> None:
        assert set(FIGURE_PROVENANCE) >= self._RUNNER_FIGURE_NAMES

    def test_every_runner_table_is_registered(self) -> None:
        assert set(TABLE_PROVENANCE) >= self._RUNNER_TABLE_NAMES

    def test_get_figure_provenance_raises_for_unregistered_name(self) -> None:
        with pytest.raises(ProvenanceError):
            get_figure_provenance("no_such_figure")

    def test_get_table_provenance_raises_for_unregistered_name(self) -> None:
        with pytest.raises(ProvenanceError):
            get_table_provenance("no_such_table")

    def test_public_benchmark_overview_is_the_only_mixed_context_figure(self) -> None:
        mixed = [name for name, r in FIGURE_PROVENANCE.items() if r.category == "mixed_context"]
        assert mixed == ["public_benchmark_overview"]
        validate_provenance(FIGURE_PROVENANCE["public_benchmark_overview"])

    def test_every_table_is_synthetic_scenario_or_operational(self) -> None:
        # Today no public source feeds any of the analysis tables directly
        # (the benchmark appendix is figures/profiles only) - if that ever
        # changes, this test forces the new table to be registered
        # deliberately rather than silently inheriting a wrong category.
        for name, record in TABLE_PROVENANCE.items():
            assert record.category in ("synthetic_operational", "synthetic_scenario"), name


class TestPublicBenchmarkOverviewIsNeverWatermarkedSynthetic:
    """The actual bug Phase 7 gate C fixes: public_benchmark_overview is
    REAL public data and must never carry credlens.analysis.charts'
    default "Synthetic data" watermark."""

    def test_public_benchmark_chart_renders_a_real_png(self, tmp_path: Path) -> None:
        profiles = [
            {"source_id": "uci-default-credit", "num_rows": 30000},
            {"source_id": "south-german-credit", "num_rows": 1000},
        ]
        out = charts.public_benchmark_overview(profiles, tmp_path / "benchmark.png")
        img = Image.open(out)
        assert img.width > 0

    def test_save_accepts_an_explicit_watermark_override(self, tmp_path: Path) -> None:
        import matplotlib.pyplot as plt

        fig, _ax = plt.subplots()
        out = charts._save(fig, tmp_path / "generic.png", watermark_text="Custom label")
        assert out.is_file()

    def test_watermark_default_is_unchanged_for_synthetic_charts(self) -> None:
        import matplotlib.pyplot as plt

        fig, _ax = plt.subplots()
        charts._watermark(fig)
        texts = [t.get_text() for t in fig.texts]
        assert any("Synthetic data" in t for t in texts)
        plt.close(fig)

    def test_public_benchmark_chart_source_uses_the_public_watermark_text(self) -> None:
        source = inspect.getsource(charts.public_benchmark_overview)
        assert "Public benchmark data - separate from the synthetic portfolio" in source
        assert '"Synthetic data - CredLens DGP' not in source
