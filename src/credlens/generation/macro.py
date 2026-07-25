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

import pandas as pd

_BCB_SOURCE_FILES: tuple[tuple[int, str, Path], ...] = (
    (20570, "bcb-sgs-20570", Path("data/raw/bcb_sgs/bcb_sgs_20570.json")),
    (21112, "bcb-sgs-21112", Path("data/raw/bcb_sgs/bcb_sgs_21112.json")),
)


def generate_macro_context(period_start: pd.Timestamp, period_end: pd.Timestamp) -> pd.DataFrame:
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

    columns = (
        "source_type",
        "source_id",
        "series_code",
        "reference_date",
        "value",
        "unit",
        "is_synthetic",
        "retrieved_at",
    )
    if not rows:
        return pd.DataFrame(columns=list(columns))
    return pd.DataFrame(rows)
