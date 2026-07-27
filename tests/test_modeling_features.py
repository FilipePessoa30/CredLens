"""Tests for credlens.modeling.features (Phase 8 section 9): manual
worked examples, safe division, no infinities/NaN, determinism, and no
future information."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from credlens.modeling.data import load_uci_default_credit
from credlens.modeling.features import FEATURE_COLUMNS, engineer_features


def _value(out: pd.DataFrame, column: str) -> float:
    return float(out[column].to_numpy()[0])


def _one_row(**overrides: float) -> pd.DataFrame:
    base = {
        "X1": 10000.0,
        "X6": 0.0,
        "X7": 0.0,
        "X8": 0.0,
        "X9": 0.0,
        "X10": 0.0,
        "X11": 0.0,
        "X12": 1000.0,
        "X13": 1000.0,
        "X14": 1000.0,
        "X15": 1000.0,
        "X16": 1000.0,
        "X17": 1000.0,
        "X18": 500.0,
        "X19": 500.0,
        "X20": 500.0,
        "X21": 500.0,
        "X22": 500.0,
        "X23": 500.0,
    }
    base.update(overrides)
    return pd.DataFrame([base])


class TestManualWorkedExamples:
    def test_max_and_most_recent_delinquency(self) -> None:
        row = _one_row(X6=3, X7=1, X8=0, X9=-1, X10=-2, X11=2)
        out = engineer_features(row)
        assert out.loc[0, "max_delinquency_status"] == 3
        assert out.loc[0, "most_recent_delinquency_status"] == 3  # X6

    def test_months_delinquent_count(self) -> None:
        row = _one_row(X6=1, X7=2, X8=0, X9=-1, X10=0, X11=3)
        out = engineer_features(row)
        assert out.loc[0, "months_delinquent_count"] == 3  # X6, X7, X11 > 0

    def test_delinquency_trend_worsening(self) -> None:
        row = _one_row(X6=5, X11=0)
        out = engineer_features(row)
        assert out.loc[0, "delinquency_trend"] == pytest.approx((5 - 0) / 5.0)

    def test_consecutive_months_delinquent_is_the_longest_streak_anywhere(self) -> None:
        # X6 (most recent) back to X11 (oldest): delinquent, delinquent, not, then
        # a longer 3-month streak (X9, X10, X11) - the longest run wins, not just
        # the most-recent run.
        row = _one_row(X6=1, X7=2, X8=0, X9=1, X10=1, X11=1)
        out = engineer_features(row)
        assert out.loc[0, "consecutive_months_delinquent"] == 3

    def test_consecutive_months_delinquent_most_recent_run_only(self) -> None:
        row = _one_row(X6=1, X7=2, X8=0, X9=0, X10=0, X11=0)
        out = engineer_features(row)
        assert out.loc[0, "consecutive_months_delinquent"] == 2

    def test_zero_limit_utilization_is_safe_not_infinite(self) -> None:
        row = _one_row(X1=0.0, X12=500, X13=500, X14=500, X15=500, X16=500, X17=500)
        out = engineer_features(row)
        assert np.isfinite(_value(out, "utilization_ratio"))
        assert out.loc[0, "utilization_ratio"] == 0.0

    def test_zero_bill_full_payment_coverage(self) -> None:
        row = _one_row(X12=0, X13=0, X14=0, X15=0, X16=0, X17=0, X18=100, X19=100)
        out = engineer_features(row)
        assert out.loc[0, "payment_coverage_rate"] == 1.0
        assert out.loc[0, "payment_to_bill_ratio"] == 5.0  # capped, "fully covered"

    def test_negative_bill_and_positive_payment_never_negative_ratio(self) -> None:
        row = _one_row(X12=-500, X13=-500, X14=-500, X15=-500, X16=-500, X17=-500, X18=100)
        out = engineer_features(row)
        assert _value(out, "payment_to_bill_ratio") >= 0.0
        assert _value(out, "worst_payment_to_bill_ratio") >= 0.0

    def test_worst_payment_to_bill_ratio_picks_the_minimum(self) -> None:
        # payment[i] pairs with bill[i+1]: (X18,X13),(X19,X14),(X20,X15),(X21,X16),(X22,X17)
        row = _one_row(
            X13=1000,
            X14=1000,
            X15=1000,
            X16=1000,
            X17=1000,
            X18=100,
            X19=1000,
            X20=1000,
            X21=1000,
            X22=1000,
        )
        out = engineer_features(row)
        assert out.loc[0, "worst_payment_to_bill_ratio"] == pytest.approx(0.1)

    def test_months_without_payment(self) -> None:
        row = _one_row(X18=0, X19=0, X20=100, X21=0, X22=100, X23=100)
        out = engineer_features(row)
        assert out.loc[0, "months_without_payment"] == 3

    def test_limit_exposure_distance_negative_when_over_limit(self) -> None:
        row = _one_row(X1=1000, X12=5000, X13=5000, X14=5000, X15=5000, X16=5000, X17=5000)
        out = engineer_features(row)
        assert _value(out, "limit_exposure_distance") < 0


class TestNoInfinitiesOrNaN:
    def test_all_zero_row_is_finite(self) -> None:
        row = _one_row(
            X1=0,
            X6=0,
            X7=0,
            X8=0,
            X9=0,
            X10=0,
            X11=0,
            X12=0,
            X13=0,
            X14=0,
            X15=0,
            X16=0,
            X17=0,
            X18=0,
            X19=0,
            X20=0,
            X21=0,
            X22=0,
            X23=0,
        )
        out = engineer_features(row)
        assert np.isfinite(out.to_numpy(dtype=float)).all()

    def test_real_uci_data_is_fully_finite(self) -> None:
        df = load_uci_default_credit()
        out = engineer_features(df)
        assert out.shape == (30000, len(FEATURE_COLUMNS))
        assert np.isfinite(out.to_numpy(dtype=float)).all()

    def test_output_is_always_float_dtype(self) -> None:
        df = load_uci_default_credit().head(50)
        out = engineer_features(df)
        assert all(dtype == np.float64 for dtype in out.dtypes)


class TestDeterminism:
    def test_same_input_produces_identical_output(self) -> None:
        df = load_uci_default_credit().head(500)
        first = engineer_features(df)
        second = engineer_features(df)
        pd.testing.assert_frame_equal(first, second)

    def test_row_order_independent(self) -> None:
        df = load_uci_default_credit().head(20)
        shuffled = df.iloc[::-1].reset_index(drop=True)
        first = engineer_features(df).reset_index(drop=True)
        second = engineer_features(shuffled).reset_index(drop=True)
        second = second.iloc[::-1].reset_index(drop=True)
        pd.testing.assert_frame_equal(first, second)


def test_feature_columns_are_never_raw_uci_columns() -> None:
    raw_columns = {f"X{i}" for i in range(1, 24)} | {"ID", "Y"}
    assert not (set(FEATURE_COLUMNS) & raw_columns)
