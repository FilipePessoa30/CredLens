"""Tests for credlens.dashboard.filters (Phase 7 section 12): options are
derived from actual data (never hardcoded), filters never raise on a
missing column, an empty selection produces an empty result (not an
error), and applying an irrelevant filter to a table without that
dimension leaves it untouched."""

from __future__ import annotations

import pandas as pd

from credlens.dashboard.data_access import DashboardData
from credlens.dashboard.filters import (
    FilterState,
    apply_filters,
    derive_filter_options,
    is_empty_result,
)


class TestApplyFilters:
    def test_no_filters_returns_the_same_rows(self) -> None:
        df = pd.DataFrame({"scenario": ["baseline", "policy_expansion"], "value": [1, 2]})
        result = apply_filters(df, FilterState())
        assert len(result) == 2

    def test_selecting_one_scenario_narrows_rows(self) -> None:
        df = pd.DataFrame({"scenario": ["baseline", "policy_expansion"], "value": [1, 2]})
        result = apply_filters(df, FilterState(scenarios=["baseline"]))
        assert list(result["scenario"]) == ["baseline"]

    def test_selecting_a_nonexistent_value_produces_empty_result_not_error(self) -> None:
        df = pd.DataFrame({"scenario": ["baseline"], "value": [1]})
        result = apply_filters(df, FilterState(scenarios=["macroeconomic_stress"]))
        assert is_empty_result(result)

    def test_filter_on_absent_column_leaves_table_untouched(self) -> None:
        df = pd.DataFrame({"snapshot_date": ["2024-01-31"], "outstanding_balance": [100.0]})
        result = apply_filters(df, FilterState(channels=["app"]))
        assert len(result) == 1

    def test_date_range_filters_by_first_matching_date_column(self) -> None:
        df = pd.DataFrame(
            {
                "snapshot_date": ["2024-01-31", "2024-06-30", "2024-12-31"],
                "value": [1, 2, 3],
            }
        )
        result = apply_filters(df, FilterState(date_range=("2024-05-01", "2024-07-01")))
        assert list(result["value"]) == [2]

    def test_multiple_filters_combine_with_and(self) -> None:
        df = pd.DataFrame(
            {
                "scenario": ["baseline", "baseline", "policy_expansion"],
                "channel": ["app", "web", "app"],
                "value": [1, 2, 3],
            }
        )
        result = apply_filters(df, FilterState(scenarios=["baseline"], channels=["web"]))
        assert list(result["value"]) == [2]


class TestIsEmptyResult:
    def test_none_is_empty(self) -> None:
        assert is_empty_result(None) is True

    def test_empty_dataframe_is_empty(self) -> None:
        assert is_empty_result(pd.DataFrame()) is True

    def test_nonempty_dataframe_is_not_empty(self) -> None:
        assert is_empty_result(pd.DataFrame({"a": [1]})) is False


def _dashboard_data(tables: dict[str, pd.DataFrame]) -> DashboardData:
    return DashboardData(
        mode="demo",
        fingerprint="f" * 64,
        build_id="BUILD_x",
        suite_id=None,
        tables=tables,
        composition={},
        insights=[],
    )


class TestDeriveFilterOptionsMissingData:
    def test_missing_table_yields_empty_options(self) -> None:
        options = derive_filter_options(_dashboard_data({}))
        assert options.channels == []
        assert options.date_min is None
        assert options.date_max is None

    def test_missing_column_yields_empty_options(self) -> None:
        data = _dashboard_data(
            {
                "funnel_monthly": pd.DataFrame({"scenario": ["baseline"]}),
                "portfolio_monthly": pd.DataFrame({"scenario": ["baseline"]}),
            }
        )
        options = derive_filter_options(data)
        assert options.channels == []
        assert options.date_min is None

    def test_all_unparseable_dates_yields_none_bounds(self) -> None:
        data = _dashboard_data(
            {"portfolio_monthly": pd.DataFrame({"snapshot_date": ["not-a-date", "also-not"]})}
        )
        options = derive_filter_options(data)
        assert options.date_min is None
        assert options.date_max is None

    def test_real_data_yields_populated_options(self) -> None:
        data = _dashboard_data(
            {
                "funnel_monthly": pd.DataFrame({"channel": ["app", "web"]}),
                "portfolio_monthly": pd.DataFrame({"snapshot_date": ["2024-01-31", "2024-02-29"]}),
            }
        )
        options = derive_filter_options(data)
        assert options.channels == ["app", "web"]
        assert options.date_min == "2024-01-31"
        assert options.date_max == "2024-02-29"
