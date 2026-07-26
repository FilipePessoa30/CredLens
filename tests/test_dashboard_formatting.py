"""Tests for credlens.dashboard.formatting (Phase 7 section 14): every
formatter must handle missing values gracefully (never raise, never
display NaN/Infinity), and synthetic amounts must never be labeled R$."""

from __future__ import annotations

import math
from datetime import date, datetime

from credlens.dashboard.formatting import (
    MISSING_VALUE_DISPLAY,
    format_bps,
    format_count,
    format_date,
    format_delta_abs,
    format_delta_rel,
    format_mob,
    format_percent,
    format_public_source_value,
    format_synthetic_money,
    safe_ratio,
)


class TestMissingValueHandling:
    def test_none_is_missing_everywhere(self) -> None:
        for fn in (
            format_count,
            format_percent,
            format_bps,
            format_synthetic_money,
            format_mob,
            format_delta_abs,
            format_delta_rel,
        ):
            assert fn(None) == MISSING_VALUE_DISPLAY

    def test_nan_is_missing_everywhere(self) -> None:
        for fn in (format_count, format_percent, format_synthetic_money):
            assert fn(float("nan")) == MISSING_VALUE_DISPLAY

    def test_no_formatter_ever_prints_nan_or_inf_literally(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf"), None):
            for fn in (format_count, format_percent, format_synthetic_money, format_mob):
                out = fn(value)
                assert out == MISSING_VALUE_DISPLAY


class TestSyntheticMoneyNeverUsesRealCurrencySymbol:
    def test_no_brl_symbol(self) -> None:
        out = format_synthetic_money(1234.5)
        assert "R$" not in out
        assert "synthetic monetary units" in out


class TestSafeRatio:
    def test_zero_denominator_returns_none_not_inf(self) -> None:
        assert safe_ratio(5, 0) is None

    def test_none_inputs_return_none(self) -> None:
        assert safe_ratio(None, 5) is None
        assert safe_ratio(5, None) is None

    def test_normal_division(self) -> None:
        assert safe_ratio(1, 4) == 0.25

    def test_never_raises_zero_division(self) -> None:
        # The whole point of safe_ratio - must never raise.
        result = safe_ratio(1, 0)
        assert result is None


class TestFormatBps:
    def test_small_delta_shown_in_bps(self) -> None:
        out = format_bps(0.0001)
        assert "bps" in out


class TestFormatDelta:
    def test_positive_delta_has_explicit_sign(self) -> None:
        assert format_delta_abs(5).startswith("+")

    def test_negative_delta_has_explicit_sign(self) -> None:
        assert format_delta_abs(-5).startswith("-")

    def test_percent_delta_uses_pp_suffix(self) -> None:
        out = format_delta_abs(0.05, as_percent=True)
        assert "pp" in out


class TestFormatMob:
    def test_formats_as_mob_n(self) -> None:
        assert format_mob(3) == "MOB 3"


class TestFormatDeltaRel:
    def test_positive_relative_delta_has_explicit_sign_and_percent(self) -> None:
        out = format_delta_rel(0.10)
        assert out.startswith("+")
        assert out.endswith("%")

    def test_negative_relative_delta(self) -> None:
        out = format_delta_rel(-0.10)
        assert out.startswith("-")


class TestFormatDate:
    def test_datetime_object_is_formatted_as_isoformat(self) -> None:
        assert format_date(date(2026, 1, 15)) == "2026-01-15"
        assert format_date(datetime(2026, 1, 15, 10, 30)).startswith("2026-01-15")

    def test_string_value_passes_through(self) -> None:
        assert format_date("2026-01-15") == "2026-01-15"

    def test_missing_value(self) -> None:
        assert format_date(None) == MISSING_VALUE_DISPLAY


class TestFormatPublicSourceValue:
    def test_numeric_value_gets_comma_formatting_and_unit(self) -> None:
        out = format_public_source_value(30000, "rows")
        assert out == "30,000 rows"

    def test_non_numeric_value_passes_through_with_unit(self) -> None:
        out = format_public_source_value("Taiwan", "population")
        assert out == "Taiwan population"

    def test_missing_value(self) -> None:
        assert format_public_source_value(None, "rows") == MISSING_VALUE_DISPLAY


def test_format_count_handles_infinity_without_raising() -> None:
    # int(inf) raises OverflowError in plain Python - format_count must
    # not propagate that to a dashboard card.
    assert format_count(math.inf) == MISSING_VALUE_DISPLAY
