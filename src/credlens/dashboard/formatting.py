"""Central formatting rules for the dashboard (Phase 7 section 14).

Every number the dashboard displays must go through one of these
functions - no page/component formats a number inline, so a unit/
rounding convention only ever needs to change in one place.

Synthetic monetary amounts are NEVER labeled "R$" (the DGP does not
declare BRL as its unit - see docs/glossary.md); they use the explicit
"Synthetic monetary units" convention instead. Values sourced from a
public benchmark use that source's own declared unit (handled by the
caller passing `unit=`, not by this module guessing).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

MISSING_VALUE_DISPLAY = "n/a"


def _is_missing(value: Any) -> bool:
    """NaN and +/-Infinity are both treated as "missing" for display
    purposes - a dashboard card must never render "nan"/"inf" or raise
    (e.g. `int(float("inf"))` raises OverflowError) - Phase 7 section 20:
    "ausencia de NaN/Infinity exibidos"."""
    if value is None:
        return True
    if isinstance(value, float):
        import math

        return math.isnan(value) or math.isinf(value)
    return False


def format_count(value: Any) -> str:
    if _is_missing(value):
        return MISSING_VALUE_DISPLAY
    return f"{int(value):,}"


def format_percent(value: Any, decimals: int = 2) -> str:
    if _is_missing(value):
        return MISSING_VALUE_DISPLAY
    return f"{float(value) * 100:.{decimals}f}%"


def format_bps(value: Any) -> str:
    """Basis points - useful for small deltas where a percent would
    round to 0.00%."""
    if _is_missing(value):
        return MISSING_VALUE_DISPLAY
    return f"{float(value) * 10_000:+.1f} bps"


def format_synthetic_money(value: Any, decimals: int = 2) -> str:
    if _is_missing(value):
        return MISSING_VALUE_DISPLAY
    return f"{float(value):,.{decimals}f} synthetic monetary units"


def format_public_source_value(value: Any, unit: str) -> str:
    """For a value sourced from a public benchmark/market-context
    dataset - uses that source's OWN declared unit, never a synthetic
    label (Phase 7 gate C)."""
    if _is_missing(value):
        return MISSING_VALUE_DISPLAY
    return f"{value:,} {unit}" if isinstance(value, int | float) else f"{value} {unit}"


def format_date(value: Any) -> str:
    if _is_missing(value):
        return MISSING_VALUE_DISPLAY
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def format_mob(value: Any) -> str:
    if _is_missing(value):
        return MISSING_VALUE_DISPLAY
    return f"MOB {int(value)}"


def format_delta_abs(value: Any, *, as_percent: bool = False, decimals: int = 2) -> str:
    if _is_missing(value):
        return MISSING_VALUE_DISPLAY
    v = float(value)
    if as_percent:
        return f"{v * 100:+.{decimals}f} pp"
    return f"{v:+,.{decimals}f}"


def format_delta_rel(value: Any, decimals: int = 1) -> str:
    if _is_missing(value):
        return MISSING_VALUE_DISPLAY
    return f"{float(value) * 100:+.{decimals}f}%"


def safe_ratio(numerator: Any, denominator: Any) -> float | None:
    """Division that returns None (never raises, never inf/NaN) when
    the denominator is zero or missing - every dashboard ratio must go
    through this, never a bare `a / b`."""
    if _is_missing(numerator) or _is_missing(denominator):
        return None
    denominator_f = float(denominator)
    if denominator_f == 0.0:
        return None
    numerator_f = float(numerator)
    result: float = numerator_f / denominator_f
    return result
