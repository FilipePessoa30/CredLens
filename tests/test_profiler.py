"""Tests for credlens.data.profiler: structural profiling of a DataFrame."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from credlens.data.profiler import profile_dataframe


def test_profile_dataframe_reports_row_and_column_counts() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})

    report = profile_dataframe(df, source_id="fixture")

    assert report.num_rows == 3
    assert report.num_columns == 2
    assert report.column_names == ["a", "b"]
    assert report.source_id == "fixture"


def test_profile_dataframe_counts_missing_values() -> None:
    df = pd.DataFrame({"a": [1, None, 3, None]})

    report = profile_dataframe(df, source_id="fixture")

    col = report.column("a")
    assert col.missing_count == 2
    assert col.missing_pct == 50.0


def test_profile_dataframe_detects_constant_column() -> None:
    df = pd.DataFrame({"a": [7, 7, 7, 7]})

    report = profile_dataframe(df, source_id="fixture")

    assert report.column("a").is_constant is True


def test_profile_dataframe_detects_non_constant_column() -> None:
    df = pd.DataFrame({"a": [1, 2, 3, 4]})

    report = profile_dataframe(df, source_id="fixture")

    assert report.column("a").is_constant is False


def test_profile_dataframe_detects_possible_identifier() -> None:
    df = pd.DataFrame({"id": [1, 2, 3, 4], "value": ["a", "a", "b", "b"]})

    report = profile_dataframe(df, source_id="fixture")

    assert report.column("id").is_possible_identifier is True
    assert report.column("value").is_possible_identifier is False


def test_profile_dataframe_identifier_requires_no_missing_values() -> None:
    # 4 rows, 4 distinct non-null values, but one missing - not a true
    # identifier column since it can't uniquely key every row.
    df = pd.DataFrame({"id": [1, 2, None, 4]})

    report = profile_dataframe(df, source_id="fixture")

    assert report.column("id").is_possible_identifier is False


def test_profile_dataframe_computes_min_max_for_numeric_columns() -> None:
    df = pd.DataFrame({"a": [10, 20, 5, 15]})

    report = profile_dataframe(df, source_id="fixture")

    assert report.column("a").min_value == 5.0
    assert report.column("a").max_value == 20.0


def test_profile_dataframe_skips_min_max_for_non_numeric_columns() -> None:
    df = pd.DataFrame({"a": ["x", "y", "z"]})

    report = profile_dataframe(df, source_id="fixture")

    assert report.column("a").min_value is None
    assert report.column("a").max_value is None


def test_profile_dataframe_detects_infinite_values() -> None:
    df = pd.DataFrame({"a": [1.0, np.inf, 3.0, -np.inf]})

    report = profile_dataframe(df, source_id="fixture")

    assert report.column("a").infinite_count == 2


def test_profile_dataframe_computes_top_values_for_low_cardinality_columns() -> None:
    df = pd.DataFrame({"category": ["a", "a", "a", "b", "b", "c"]})

    report = profile_dataframe(df, source_id="fixture")

    top_values = report.column("category").top_values
    assert top_values == {"a": 3, "b": 2, "c": 1}


def test_profile_dataframe_omits_top_values_above_cardinality_threshold() -> None:
    # 31 distinct values exceeds the 30-value threshold for computing
    # top-value frequencies (would be a near-useless "top 10" on 31 singletons).
    df = pd.DataFrame({"a": list(range(31))})

    report = profile_dataframe(df, source_id="fixture")

    assert report.column("a").top_values == {}


def test_profile_dataframe_detects_exact_duplicate_rows() -> None:
    df = pd.DataFrame({"a": [1, 2, 1], "b": ["x", "y", "x"]})

    report = profile_dataframe(df, source_id="fixture")

    assert report.exact_duplicate_rows == 1


def test_profile_dataframe_zero_duplicates_when_all_rows_distinct() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})

    report = profile_dataframe(df, source_id="fixture")

    assert report.exact_duplicate_rows == 0


def test_profile_dataframe_does_not_mutate_input() -> None:
    df = pd.DataFrame({"a": [1, None, 3], "b": ["x", "y", "z"]})
    original = df.copy(deep=True)

    profile_dataframe(df, source_id="fixture")

    pd.testing.assert_frame_equal(df, original)


def test_profile_dataframe_column_lookup_raises_for_unknown_column() -> None:
    df = pd.DataFrame({"a": [1, 2, 3]})
    report = profile_dataframe(df, source_id="fixture")

    with pytest.raises(KeyError):
        report.column("does_not_exist")
