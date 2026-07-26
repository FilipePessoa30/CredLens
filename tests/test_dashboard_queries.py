"""Direct unit tests for credlens.dashboard.queries (Phase 7 section 10) -
every early-return ("no matching column"/"empty input") branch, which a
real, always-populated build/demo package never exercises on its own."""

from __future__ import annotations

import pandas as pd

from credlens.dashboard.queries import (
    approval_and_booking_rates,
    latest_snapshot_per_scenario,
    most_mature_comparable_mob,
    roll_forward_rate_from_current,
    totals_by_scenario,
)


class TestLatestSnapshotPerScenario:
    def test_empty_dataframe_passes_through(self) -> None:
        df = pd.DataFrame()
        assert latest_snapshot_per_scenario(df) is df

    def test_missing_date_column_passes_through(self) -> None:
        df = pd.DataFrame({"scenario": ["baseline"]})
        assert latest_snapshot_per_scenario(df) is df

    def test_real_data_keeps_latest_row_per_scenario(self) -> None:
        df = pd.DataFrame(
            {
                "scenario": ["baseline", "baseline"],
                "snapshot_date": ["2024-01-31", "2024-02-29"],
                "value": [1, 2],
            }
        )
        out = latest_snapshot_per_scenario(df)
        assert list(out["value"]) == [2]


class TestTotalsByScenario:
    def test_empty_dataframe_passes_through(self) -> None:
        df = pd.DataFrame()
        assert totals_by_scenario(df, ["x"]) is df

    def test_no_matching_sum_columns_passes_through(self) -> None:
        df = pd.DataFrame({"scenario": ["baseline"], "other": [1]})
        assert totals_by_scenario(df, ["not_present"]) is df

    def test_real_data_sums_by_scenario(self) -> None:
        df = pd.DataFrame({"scenario": ["baseline", "baseline"], "value": [1, 2]})
        out = totals_by_scenario(df, ["value"])
        assert out["value"].iloc[0] == 3


class TestApprovalAndBookingRates:
    def test_missing_columns_leaves_totals_unchanged(self) -> None:
        totals = pd.DataFrame({"scenario": ["baseline"]})
        out = approval_and_booking_rates(totals)
        assert "approval_rate" not in out.columns
        assert "booking_rate" not in out.columns

    def test_real_columns_add_rates(self) -> None:
        totals = pd.DataFrame(
            {
                "approved_count": [50],
                "decisioned_applications": [100],
                "booked_count": [40],
            }
        )
        out = approval_and_booking_rates(totals)
        assert out["approval_rate"].iloc[0] == 0.5
        assert out["booking_rate"].iloc[0] == 0.8


class TestMostMatureComparableMob:
    def test_empty_dataframe_returns_none(self) -> None:
        assert most_mature_comparable_mob(pd.DataFrame()) is None

    def test_missing_column_returns_none(self) -> None:
        assert most_mature_comparable_mob(pd.DataFrame({"x": [1]})) is None

    def test_real_data_returns_the_minimum_max_mob(self) -> None:
        df = pd.DataFrame({"max_mob_observed_for_cohort": [3, 5, 2]})
        assert most_mature_comparable_mob(df) == 2


class TestRollForwardRateFromCurrent:
    def test_no_current_bucket_rows_returns_none(self) -> None:
        df = pd.DataFrame({"from_bucket": ["30-59"], "to_bucket": ["60-89"], "contract_count": [1]})
        assert roll_forward_rate_from_current(df) is None

    def test_real_data_computes_a_rate(self) -> None:
        df = pd.DataFrame(
            {
                "from_bucket": ["current", "current"],
                "to_bucket": ["current", "1-29"],
                "contract_count": [90, 10],
            }
        )
        rate = roll_forward_rate_from_current(df)
        assert rate == 0.1
