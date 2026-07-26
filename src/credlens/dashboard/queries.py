"""Display-shaping helpers over already-loaded, already-filtered
DataFrames (Phase 7 section 10). These are RESHAPING operations only
(latest snapshot per scenario, totals per scenario) - never a new business
metric; every underlying number still comes straight from
`credlens.analysis.metrics`/the dbt marts. No SQL is built here.
"""

from __future__ import annotations

import pandas as pd

from credlens.dashboard.formatting import safe_ratio


def latest_snapshot_per_scenario(
    df: pd.DataFrame, date_column: str = "snapshot_date"
) -> pd.DataFrame:
    """One row per scenario: the most recent date each scenario's own
    data reaches - never mixes dates across scenarios (Phase 6/7's STOCK-
    metric grain rule)."""
    if df.empty or date_column not in df.columns or "scenario" not in df.columns:
        return df
    idx = df.groupby("scenario")[date_column].idxmax()
    return df.loc[idx].reset_index(drop=True)


def totals_by_scenario(df: pd.DataFrame, sum_columns: list[str]) -> pd.DataFrame:
    if df.empty or "scenario" not in df.columns:
        return df
    present = [c for c in sum_columns if c in df.columns]
    if not present:
        return df
    return df.groupby("scenario", as_index=False)[present].sum()


def approval_and_booking_rates(totals: pd.DataFrame) -> pd.DataFrame:
    """Adds approval_rate/booking_rate columns to an already-summed
    funnel totals table - a display ratio, computed with
    `safe_ratio` (never divides by zero)."""
    out = totals.copy()
    if {"approved_count", "decisioned_applications"} <= set(out.columns):
        out["approval_rate"] = [
            safe_ratio(a, d)
            for a, d in zip(out["approved_count"], out["decisioned_applications"], strict=True)
        ]
    if {"booked_count", "approved_count"} <= set(out.columns):
        out["booking_rate"] = [
            safe_ratio(b, a)
            for b, a in zip(out["booked_count"], out["approved_count"], strict=True)
        ]
    return out


def most_mature_comparable_mob(vintage_df: pd.DataFrame) -> int | None:
    """The largest months_on_book every origination cohort has reached -
    the only MOB at which cross-cohort comparison is valid (Phase 6
    vintage-maturity rule)."""
    if vintage_df.empty or "max_mob_observed_for_cohort" not in vintage_df.columns:
        return None
    return int(vintage_df["max_mob_observed_for_cohort"].min())


def roll_forward_rate_from_current(roll_rates_df: pd.DataFrame) -> float | None:
    from_current = roll_rates_df[roll_rates_df.get("from_bucket") == "current"]
    if from_current.empty:
        return None
    total = float(from_current["contract_count"].sum())
    stayed = float(from_current.loc[from_current["to_bucket"] == "current", "contract_count"].sum())
    return safe_ratio(total - stayed, total)
