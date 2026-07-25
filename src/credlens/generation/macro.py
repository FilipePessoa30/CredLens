"""Re-expresses the already-acquired, real BCB SGS series at
macro_context_monthly's operational grain - never invents, extrapolates,
or synthesizes a macro value in the baseline scenario (that is exactly
what the still-locked macroeconomic_stress scenario would add later, via
source_type=synthetic_shock rows - see docs/adr/0008).

Reads directly from the Phase 2 raw acquisition (data/raw/bcb_sgs/*.json)
- never modifies those files, never re-downloads them. If a file is
missing (e.g. a fresh clone without `credlens data fetch` having been
run), macro context is simply empty for that series rather than raising -
this generator never invents a substitute for real data it doesn't have.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from credlens.generation.config import MacroShockConfig

_BCB_SOURCE_FILES: tuple[tuple[int, str, Path], ...] = (
    (20570, "bcb-sgs-20570", Path("data/raw/bcb_sgs/bcb_sgs_20570.json")),
    (21112, "bcb-sgs-21112", Path("data/raw/bcb_sgs/bcb_sgs_21112.json")),
)

_COLUMNS = (
    "source_type",
    "source_id",
    "series_code",
    "reference_date",
    "value",
    "unit",
    "is_synthetic",
    "retrieved_at",
)


def generate_macro_context(
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
    shock: MacroShockConfig | None = None,
) -> pd.DataFrame:
    """The real BCB rows (never invented) plus, ONLY when `shock` is given
    (macroeconomic_stress, Phase 4B), additional explicitly-synthetic rows
    for the shock window - added as EXTRA rows with their own
    source_type/source_id, never merged into or overwriting a real BCB
    row (macro_context_monthly's primary key is
    (source_type, source_id, reference_date), so a synthetic and a real
    row for the same month never collide). See docs/adr/0008 and
    docs/counterfactual_scenarios.md."""
    rows: list[dict[str, object]] = []
    for series_code, source_id, path in _BCB_SOURCE_FILES:
        if not path.is_file():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        for entry in raw:
            reference_date = pd.to_datetime(entry["data"], format="%d/%m/%Y")
            if not (period_start <= reference_date <= period_end):
                continue
            rows.append(
                {
                    "source_type": "public_bcb_observation",
                    "source_id": source_id,
                    "series_code": series_code,
                    "reference_date": reference_date.strftime("%Y-%m-%d"),
                    "value": float(entry["valor"]),
                    "unit": "currency_unit millions" if series_code == 20570 else "percent",
                    "is_synthetic": False,
                    "retrieved_at": None,
                }
            )

    if shock is not None:
        shock_start = pd.Timestamp(shock.shock_date)
        for reference_date in pd.date_range(start=shock_start, end=period_end, freq="MS"):
            if not (period_start <= reference_date <= period_end):
                continue
            rows.append(
                {
                    # "synthetic_shock" - matches the domain already
                    # declared on macro_context_monthly.source_type (see
                    # contracts/operational/macro_context_monthly.yaml,
                    # anticipated in Phase 4A's ADR-0008 for exactly this
                    # scenario) rather than inventing a new value.
                    "source_type": "synthetic_shock",
                    "source_id": shock.synthetic_source_id,
                    "series_code": None,
                    "reference_date": reference_date.strftime("%Y-%m-%d"),
                    "value": float(shock.synthetic_shock_value),
                    "unit": "synthetic_stress_index",
                    "is_synthetic": True,
                    "retrieved_at": None,
                }
            )

    if not rows:
        return pd.DataFrame(columns=list(_COLUMNS))
    return pd.DataFrame(rows)
