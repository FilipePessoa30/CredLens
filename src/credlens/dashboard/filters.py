"""Dashboard filter state and application (Phase 7 section 12).

`FilterOptions` is DERIVED from whatever data is actually loaded (never a
hardcoded list) so a filter can never offer a value that does not exist
in the current build/demo package. `apply_filters` only touches a
DataFrame's own columns - a table without a given dimension (e.g.
`portfolio_monthly` has no `channel`) is simply left unfiltered on that
dimension, never raises.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from credlens.dashboard.data_access import DashboardData


@dataclass(frozen=True)
class FilterOptions:
    scenarios: list[str]
    channels: list[str]
    products: list[str]
    regions: list[str]
    policy_versions: list[str]
    bureau_score_buckets: list[str]
    income_bands: list[str]
    contract_value_bands: list[str]
    vintage_months: list[str]
    dpd_buckets: list[str]
    date_min: str | None
    date_max: str | None


@dataclass
class FilterState:
    scenarios: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    policy_versions: list[str] = field(default_factory=list)
    bureau_score_buckets: list[str] = field(default_factory=list)
    income_bands: list[str] = field(default_factory=list)
    contract_value_bands: list[str] = field(default_factory=list)
    vintage_months: list[str] = field(default_factory=list)
    dpd_buckets: list[str] = field(default_factory=list)
    date_range: tuple[str, str] | None = None


def derive_filter_options(data: DashboardData) -> FilterOptions:
    def _unique_sorted(table: str, column: str) -> list[str]:
        df = data.tables.get(table)
        if df is None or column not in df.columns:
            return []
        return sorted(str(v) for v in df[column].dropna().unique())

    def _date_bounds(table: str, column: str) -> tuple[str | None, str | None]:
        df = data.tables.get(table)
        if df is None or column not in df.columns or df.empty:
            return None, None
        dates = pd.to_datetime(df[column], errors="coerce").dropna()
        if dates.empty:
            return None, None
        return str(dates.min().date()), str(dates.max().date())

    date_min, date_max = _date_bounds("portfolio_monthly", "snapshot_date")

    return FilterOptions(
        scenarios=_unique_sorted("scenario_comparison", "scenario") or ["baseline"],
        channels=_unique_sorted("funnel_monthly", "channel"),
        products=_unique_sorted("credit_risk_segment_summary", "product"),
        regions=_unique_sorted("portfolio_by_region_and_channel", "region"),
        policy_versions=_unique_sorted("policy_version_comparison", "policy_version_id"),
        bureau_score_buckets=_unique_sorted("credit_risk_segment_summary", "bureau_score_bucket"),
        income_bands=_unique_sorted("credit_risk_segment_summary", "income_band"),
        contract_value_bands=_unique_sorted("credit_risk_segment_summary", "contract_value_band"),
        vintage_months=_unique_sorted("vintage_cohorts", "vintage_month"),
        dpd_buckets=_unique_sorted("roll_rates", "to_bucket"),
        date_min=date_min,
        date_max=date_max,
    )


_FILTER_COLUMN_MAP: dict[str, str] = {
    "scenarios": "scenario",
    "channels": "channel",
    "products": "product",
    "regions": "region",
    "policy_versions": "policy_version_id",
    "bureau_score_buckets": "bureau_score_bucket",
    "income_bands": "income_band",
    "contract_value_bands": "contract_value_band",
    "vintage_months": "vintage_month",
    "dpd_buckets": "to_bucket",
}


def apply_filters(df: pd.DataFrame, state: FilterState) -> pd.DataFrame:
    """Applies every selected filter whose column is actually present in
    `df` - a table without a given dimension is left untouched on that
    dimension (never raises, never silently drops all rows because of an
    irrelevant filter). An empty selection for a present dimension means
    "no rows match" (an explicit empty state, not an error - Phase 7
    section 12: "selecao vazia deve produzir estado vazio, nao erro")."""
    result = df
    for attr, column in _FILTER_COLUMN_MAP.items():
        selected: list[str] = getattr(state, attr)
        if column not in result.columns:
            continue
        if selected:
            result = result[result[column].astype(str).isin(selected)]

    if state.date_range is not None:
        for date_col in ("snapshot_date", "submitted_month", "event_month", "write_off_month"):
            if date_col in result.columns:
                start, end = state.date_range
                dates = pd.to_datetime(result[date_col], errors="coerce")
                mask = (dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))
                result = result[mask]
                break

    return result


def is_empty_result(df: pd.DataFrame | None) -> bool:
    return df is None or df.empty
