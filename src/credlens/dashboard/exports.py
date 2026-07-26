"""Export helpers (Phase 7 section 17). Every export writes (or returns,
for Streamlit's own download button) a metadata sidecar alongside the
data - build id, analysis id, filters, timestamp, provenance, sample size
- so a downloaded file is never separated from its own provenance.

Never exports customer/contract-level rows - only the already-aggregate
tables the dashboard itself reads (Phase 7 section 17: "Nao exporte
tabelas detalhadas de clientes").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import plotly.graph_objects as go

_FORBIDDEN_EXPORT_COLUMNS = frozenset(
    {"contract_key", "contract_id", "customer_key", "customer_id", "application_id"}
)


class ExportError(Exception):
    """Raised when an export would violate an aggregate-only/provenance rule."""


@dataclass(frozen=True)
class ExportMetadata:
    build_id: str
    analysis_id: str | None
    fingerprint: str
    filters: dict[str, Any]
    provenance_label: str
    sample_size: int | None
    exported_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "build_id": self.build_id,
            "analysis_id": self.analysis_id,
            "fingerprint": self.fingerprint,
            "filters": self.filters,
            "provenance_label": self.provenance_label,
            "sample_size": self.sample_size,
            "exported_at": self.exported_at,
        }


def new_export_metadata(
    *,
    build_id: str,
    analysis_id: str | None,
    fingerprint: str,
    filters: dict[str, Any],
    provenance_label: str,
    sample_size: int | None,
) -> ExportMetadata:
    return ExportMetadata(
        build_id=build_id,
        analysis_id=analysis_id,
        fingerprint=fingerprint,
        filters=filters,
        provenance_label=provenance_label,
        sample_size=sample_size,
        exported_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def table_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Refuses to export a table carrying a customer/contract-identifying
    column - only aggregate breakdowns may leave the dashboard."""
    forbidden_present = _FORBIDDEN_EXPORT_COLUMNS & set(df.columns)
    if forbidden_present:
        raise ExportError(
            f"Refusing to export a table with column(s) {sorted(forbidden_present)} - only "
            "aggregate tables may be exported from the dashboard."
        )
    return df.to_csv(index=False).encode("utf-8")


def metadata_to_json_bytes(metadata: ExportMetadata) -> bytes:
    return json.dumps(metadata.to_dict(), indent=2, sort_keys=True).encode("utf-8")


def figure_to_png_bytes(fig: go.Figure) -> bytes | None:
    """Returns None (never raises) if the figure cannot be rendered to
    PNG in this environment (Phase 7 section 17: "quando tecnicamente
    viavel") - callers must handle a None return by hiding the PNG
    download option rather than showing a broken button."""
    try:
        result: bytes = fig.to_image(format="png", scale=2)
        return result
    except Exception:
        return None
