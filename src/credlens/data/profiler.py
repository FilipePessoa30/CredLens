"""Reproducible, read-only structural profiling of a raw tabular dataset.

Computes descriptive statistics only. It never modifies its input: no
imputation, no deduplication, no renaming, no recoding, no
normalization - see docs/data_quality_audit.md for how this output is
interpreted, and the Phase 2 rule that raw data is never "corrected" in
place.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

_TOP_N_CATEGORIES = 10
_CATEGORICAL_CARDINALITY_THRESHOLD = 30


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    dtype: str
    missing_count: int
    missing_pct: float
    cardinality: int
    is_constant: bool
    is_possible_identifier: bool
    min_value: float | None
    max_value: float | None
    infinite_count: int
    top_values: dict[str, int]  # only populated below the cardinality threshold


@dataclass(frozen=True)
class ProfileReport:
    source_id: str
    num_rows: int
    num_columns: int
    column_names: list[str]
    exact_duplicate_rows: int
    columns: list[ColumnProfile]

    def column(self, name: str) -> ColumnProfile:
        for profile in self.columns:
            if profile.name == name:
                return profile
        raise KeyError(name)


def _profile_column(series: pd.Series, num_rows: int) -> ColumnProfile:
    missing_count = int(series.isna().sum())
    missing_pct = round((missing_count / num_rows * 100.0), 4) if num_rows else 0.0
    non_null = series.dropna()
    cardinality = int(non_null.nunique())
    is_constant = cardinality <= 1
    is_possible_identifier = num_rows > 0 and missing_count == 0 and cardinality == num_rows

    is_numeric = bool(pd.api.types.is_numeric_dtype(series))
    min_value: float | None = None
    max_value: float | None = None
    infinite_count = 0
    if is_numeric and not non_null.empty:
        numeric_values = non_null.to_numpy(dtype=float)
        min_value = float(numeric_values.min())
        max_value = float(numeric_values.max())
        infinite_count = int(np.isinf(numeric_values).sum())

    top_values: dict[str, int] = {}
    if 0 < cardinality <= _CATEGORICAL_CARDINALITY_THRESHOLD:
        counts = non_null.value_counts().head(_TOP_N_CATEGORIES)
        top_values = {str(key): int(value) for key, value in counts.items()}

    return ColumnProfile(
        name=str(series.name),
        dtype=str(series.dtype),
        missing_count=missing_count,
        missing_pct=missing_pct,
        cardinality=cardinality,
        is_constant=is_constant,
        is_possible_identifier=is_possible_identifier,
        min_value=min_value,
        max_value=max_value,
        infinite_count=infinite_count,
        top_values=top_values,
    )


def profile_dataframe(df: pd.DataFrame, *, source_id: str) -> ProfileReport:
    """Compute a structural profile of `df`. Does not mutate `df`."""
    num_rows = len(df)
    columns = [_profile_column(df[col_name], num_rows) for col_name in df.columns]
    exact_duplicate_rows = int(df.duplicated(keep="first").sum())

    return ProfileReport(
        source_id=source_id,
        num_rows=num_rows,
        num_columns=len(df.columns),
        column_names=[str(col) for col in df.columns],
        exact_duplicate_rows=exact_duplicate_rows,
        columns=columns,
    )
