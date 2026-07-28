"""Data-quality metrics (Phase 9 section 15.1) - a thin, monitoring-
facing summary over `credlens.modeling.input_contract.
InputValidationReport`, run in `audit` mode so every batch is FULLY
profiled (never blocked) before the runner decides whether to actually
score it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from credlens.modeling.input_contract import InputValidationReport


@dataclass(frozen=True)
class DataQualityResult:
    schema_valid: bool
    row_count: int
    missingness_rate: float
    duplicate_rate: float
    domain_violation_rate: float
    range_violation_rate: float
    type_violation: bool
    unexpected_categories: list[str]
    non_finite_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_valid": self.schema_valid,
            "row_count": self.row_count,
            "missingness_rate": round(self.missingness_rate, 6),
            "duplicate_rate": round(self.duplicate_rate, 6),
            "domain_violation_rate": round(self.domain_violation_rate, 6),
            "range_violation_rate": round(self.range_violation_rate, 6),
            "type_violation": self.type_violation,
            "unexpected_categories": self.unexpected_categories,
            "non_finite_rate": round(self.non_finite_rate, 6),
        }


def compute_data_quality(
    raw_batch: pd.DataFrame, report: InputValidationReport
) -> DataQualityResult:
    n = max(report.n_rows, 1)
    profile = report.impact_profile
    unexpected = [
        v.column
        for v in report.batch_level_violations
        if v.violation_type == "unexpected_extra_column" and v.column
    ]
    return DataQualityResult(
        schema_valid=not report.has_batch_level_violation,
        row_count=report.n_rows,
        missingness_rate=profile.get("non_finite_value", 0) / n,
        duplicate_rate=profile.get("duplicate_id", 0) / n,
        domain_violation_rate=profile.get("domain_violation", 0) / n,
        range_violation_rate=profile.get("range_violation", 0) / n,
        type_violation=any(
            v.violation_type == "wrong_dtype" for v in report.batch_level_violations
        ),
        unexpected_categories=unexpected,
        non_finite_rate=profile.get("non_finite_value", 0) / n,
    )
