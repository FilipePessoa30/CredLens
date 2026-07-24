"""Orchestrates structural profiling into categorized, reproducible findings.

Every finding is tagged with one of five categories so a reader can tell
apart what is actually wrong from what merely deserves a closer look:

- `confirmed_problem` - contradicts the source's own documentation, or is
  internally inconsistent (e.g. infinite values, a documented column
  missing from the file).
- `candidate_anomaly` - structurally unusual but not yet shown to be wrong
  (e.g. a constant column, an undocumented extra column, duplicate rows).
- `documented_characteristic` - matches something the source's own
  documentation already says to expect (e.g. the known ID column).
- `hypothesis_requiring_investigation` - a pattern that looks like it
  might mean something (e.g. an unexpected unique-per-row column) but
  needs a human/domain read before concluding anything.
- `structural_limitation` - not a defect, but a property of the data that
  bounds what can be built on it (e.g. a single-snapshot dataset with no
  time series).

This module never modifies the audited data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

import pandas as pd

from credlens.data.profiler import ProfileReport, profile_dataframe
from credlens.data.schema import DatasetSchema, SchemaComparison, compare_columns

FindingCategory = Literal[
    "confirmed_problem",
    "candidate_anomaly",
    "documented_characteristic",
    "hypothesis_requiring_investigation",
    "structural_limitation",
]


@dataclass(frozen=True)
class AuditFinding:
    source_id: str
    column: str | None
    category: FindingCategory
    summary: str


@dataclass(frozen=True)
class AuditReport:
    source_id: str
    generated_at_utc: str
    profile: ProfileReport
    schema_comparison: SchemaComparison | None
    findings: list[AuditFinding]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def audit_dataframe(
    df: pd.DataFrame,
    *,
    source_id: str,
    schema: DatasetSchema | None = None,
    documented_no_missing_values: bool = False,
    known_id_columns: tuple[str, ...] = (),
) -> AuditReport:
    """Profile `df` and derive categorized findings. Does not mutate `df`.

    Args:
        schema: if provided, actual columns are compared against it and
            any divergence is reported.
        documented_no_missing_values: if the source's own documentation
            claims no missing values, any missing value found is a
            `confirmed_problem` (a contradiction), not just an anomaly.
        known_id_columns: column names the source documents as an
            identifier (e.g. "ID"); a unique-per-row column matching one
            of these is a `documented_characteristic` rather than a
            `hypothesis_requiring_investigation`.
    """
    profile = profile_dataframe(df, source_id=source_id)
    findings: list[AuditFinding] = []

    schema_comparison: SchemaComparison | None = None
    if schema is not None:
        schema_comparison = compare_columns(schema, profile.column_names)
        findings.extend(
            AuditFinding(
                source_id,
                column,
                "candidate_anomaly",
                f"Column '{column}' is present in the acquired file but not documented in "
                "the recorded schema.",
            )
            for column in schema_comparison.unexpected_columns
        )
        findings.extend(
            AuditFinding(
                source_id,
                column,
                "confirmed_problem",
                f"Documented column '{column}' is missing from the acquired file.",
            )
            for column in schema_comparison.missing_columns
        )

    for col in profile.columns:
        if col.missing_count > 0:
            category: FindingCategory = (
                "confirmed_problem" if documented_no_missing_values else "candidate_anomaly"
            )
            reason = (
                "contradicting the source's documented 'no missing values'"
                if documented_no_missing_values
                else "no documentation was recorded stating whether missing values are expected"
            )
            findings.append(
                AuditFinding(
                    source_id,
                    col.name,
                    category,
                    f"{col.missing_count} missing value(s) ({col.missing_pct}%); {reason}.",
                )
            )
        if col.is_constant:
            findings.append(
                AuditFinding(
                    source_id,
                    col.name,
                    "candidate_anomaly",
                    "Column has a single distinct value across all non-missing rows "
                    "(possible constant / non-informative feature).",
                )
            )
        if col.infinite_count > 0:
            findings.append(
                AuditFinding(
                    source_id,
                    col.name,
                    "confirmed_problem",
                    f"Column contains {col.infinite_count} infinite value(s).",
                )
            )
        if col.is_possible_identifier:
            id_category: FindingCategory = (
                "documented_characteristic"
                if col.name in known_id_columns
                else "hypothesis_requiring_investigation"
            )
            id_note = (
                "matches the source's documented identifier column"
                if col.name in known_id_columns
                else "not documented as an identifier - worth confirming it is not an "
                "accidental leakage or artifact column"
            )
            findings.append(
                AuditFinding(
                    source_id,
                    col.name,
                    id_category,
                    f"Column has a unique value per row ({id_note}).",
                )
            )

    if profile.exact_duplicate_rows > 0:
        findings.append(
            AuditFinding(
                source_id,
                None,
                "candidate_anomaly",
                f"{profile.exact_duplicate_rows} exact duplicate row(s) found across all columns.",
            )
        )

    return AuditReport(
        source_id=source_id,
        generated_at_utc=datetime.now(UTC).isoformat(),
        profile=profile,
        schema_comparison=schema_comparison,
        findings=findings,
    )
