"""Tests for credlens.dashboard.exports (Phase 7 section 17): every
export carries a provenance metadata sidecar, never exports a
customer/contract-identifying column, and PNG export degrades to None
(never raises) when rendering is not possible."""

from __future__ import annotations

import json

import pandas as pd
import plotly.graph_objects as go
import pytest

from credlens.dashboard.exports import (
    ExportError,
    figure_to_png_bytes,
    metadata_to_json_bytes,
    new_export_metadata,
    table_to_csv_bytes,
)


class TestTableToCsvBytes:
    def test_exports_a_plain_aggregate_table(self) -> None:
        df = pd.DataFrame({"scenario": ["baseline"], "value": [1]})
        csv_bytes = table_to_csv_bytes(df)
        assert b"scenario" in csv_bytes
        assert b"baseline" in csv_bytes

    @pytest.mark.parametrize(
        "column", ["contract_key", "contract_id", "customer_key", "customer_id"]
    )
    def test_refuses_a_table_with_a_forbidden_column(self, column: str) -> None:
        df = pd.DataFrame({column: ["x"], "value": [1]})
        with pytest.raises(ExportError):
            table_to_csv_bytes(df)


class TestExportMetadata:
    def test_new_export_metadata_round_trips_to_json(self) -> None:
        metadata = new_export_metadata(
            build_id="BUILD_x",
            analysis_id="ANALYSIS_x",
            fingerprint="fp123",
            filters={"scenario": ["baseline"]},
            provenance_label="Synthetic data - illustrative portfolio",
            sample_size=42,
        )
        payload = json.loads(metadata_to_json_bytes(metadata))
        assert payload["build_id"] == "BUILD_x"
        assert payload["sample_size"] == 42
        assert payload["filters"] == {"scenario": ["baseline"]}
        assert "exported_at" in payload


class TestFigureToPngBytes:
    def test_real_figure_renders_to_a_valid_png(self) -> None:
        fig = go.Figure(data=go.Bar(x=["a", "b"], y=[1, 2]))
        png_bytes = figure_to_png_bytes(fig)
        assert png_bytes is not None
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_returns_none_rather_than_raising_when_rendering_fails(self) -> None:
        class _BrokenFigure:
            def to_image(self, format: str, scale: int) -> bytes:
                raise RuntimeError("no renderer available")

        result = figure_to_png_bytes(_BrokenFigure())
        assert result is None
