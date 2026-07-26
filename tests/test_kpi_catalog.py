"""Tests for warehouse/kpi_catalog.yml: the documentation-only KPI
catalog referenced (in prose only) by credlens.warehouse.reconciliation,
but never actually parsed by any code - which is exactly how a real YAML
syntax error (an unquoted value starting with `>`, and two unquoted
values containing a bare `: `) went undetected for a full phase. This
file is the structural safety net that error class needs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_CATALOG_PATH = Path("warehouse/kpi_catalog.yml")
_REQUIRED_FIELDS = ("id", "name", "category", "business_objective", "formula", "status")
# A not_supported entry legitimately has no grain/source_model - there is
# no model backing a KPI that was deliberately never implemented.
_REQUIRED_WHEN_IMPLEMENTED = ("grain", "source_model")
_VALID_STATUSES = {"implemented", "proposed", "not_supported"}


def _load_catalog() -> dict[str, Any]:
    catalog: dict[str, Any] = yaml.safe_load(_CATALOG_PATH.read_text(encoding="utf-8"))
    return catalog


class TestKpiCatalogIsValidYaml:
    def test_parses_without_error(self) -> None:
        catalog = _load_catalog()
        assert isinstance(catalog, dict)
        assert "kpis" in catalog
        assert isinstance(catalog["kpis"], list)
        assert len(catalog["kpis"]) > 0

    def test_every_entry_has_every_required_field_non_empty(self) -> None:
        catalog = _load_catalog()
        missing = [
            (entry.get("id", "<no id>"), field)
            for entry in catalog["kpis"]
            for field in _REQUIRED_FIELDS
            if not entry.get(field)
        ]
        assert missing == []

    def test_every_implemented_entry_has_a_grain_and_source_model(self) -> None:
        catalog = _load_catalog()
        missing = [
            (entry["id"], field)
            for entry in catalog["kpis"]
            if entry["status"] == "implemented"
            for field in _REQUIRED_WHEN_IMPLEMENTED
            if not entry.get(field)
        ]
        assert missing == []

    def test_every_id_is_unique(self) -> None:
        catalog = _load_catalog()
        ids = [entry["id"] for entry in catalog["kpis"]]
        assert len(ids) == len(set(ids))

    def test_every_status_is_a_recognized_value(self) -> None:
        catalog = _load_catalog()
        bad = [
            (entry["id"], entry["status"])
            for entry in catalog["kpis"]
            if entry["status"] not in _VALID_STATUSES
        ]
        assert bad == []

    def test_no_entry_is_left_proposed(self) -> None:
        """Phase 6 section 7 implemented every KPI that was still
        `proposed` (scheduled_amount and the macro pre/post-shock
        comparison) - a real dbt model+docs+tests now backs every
        `implemented` entry. A new `proposed` entry is fine to add in a
        future phase; this test only guards against silently leaving one
        stale."""
        catalog = _load_catalog()
        proposed = [entry["id"] for entry in catalog["kpis"] if entry["status"] == "proposed"]
        assert proposed == [], f"unexpectedly still proposed: {proposed}"
