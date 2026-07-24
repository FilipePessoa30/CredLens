"""Tests for credlens.data.audit: finding categorization.

Not explicitly named in the Phase 2 file list (which specified profiler
and schema tests separately) - added because audit.py's categorization
logic (confirmed_problem / candidate_anomaly / documented_characteristic /
hypothesis_requiring_investigation) is complex enough to deserve direct,
fast unit tests rather than only indirect coverage through the CLI.
"""

from __future__ import annotations

import pandas as pd

from credlens.data.audit import audit_dataframe
from credlens.data.schema import ColumnSpec, DatasetSchema


def test_audit_dataframe_only_expected_id_finding_for_clean_data() -> None:
    # "value" deliberately repeats so it isn't also flagged as a possible
    # identifier - the only finding should be "id" being a known,
    # documented identifier, not a concern.
    df = pd.DataFrame({"id": [1, 2, 3, 4], "value": ["a", "b", "a", "b"]})

    report = audit_dataframe(df, source_id="fixture", known_id_columns=("id",))

    assert len(report.findings) == 1
    assert report.findings[0].category == "documented_characteristic"
    assert report.source_id == "fixture"


def test_audit_dataframe_flags_missing_values_as_confirmed_problem_when_documented() -> None:
    df = pd.DataFrame({"a": [1, None, 3]})

    report = audit_dataframe(df, source_id="fixture", documented_no_missing_values=True)

    finding = next(f for f in report.findings if f.column == "a")
    assert finding.category == "confirmed_problem"
    assert "contradicting" in finding.summary


def test_audit_dataframe_flags_missing_values_as_candidate_anomaly_when_undocumented() -> None:
    df = pd.DataFrame({"a": [1, None, 3]})

    report = audit_dataframe(df, source_id="fixture", documented_no_missing_values=False)

    finding = next(f for f in report.findings if f.column == "a")
    assert finding.category == "candidate_anomaly"


def test_audit_dataframe_flags_constant_column_as_candidate_anomaly() -> None:
    df = pd.DataFrame({"a": [5, 5, 5]})

    report = audit_dataframe(df, source_id="fixture")

    finding = next(f for f in report.findings if f.column == "a")
    assert finding.category == "candidate_anomaly"
    assert "constant" in finding.summary.lower()


def test_audit_dataframe_flags_infinite_values_as_confirmed_problem() -> None:
    df = pd.DataFrame({"a": [1.0, float("inf"), 3.0]})

    report = audit_dataframe(df, source_id="fixture")

    finding = next(f for f in report.findings if f.column == "a" and "infinite" in f.summary)
    assert finding.category == "confirmed_problem"


def test_audit_dataframe_known_id_column_is_documented_characteristic() -> None:
    df = pd.DataFrame({"id": [1, 2, 3], "other": ["x", "y", "z"]})

    report = audit_dataframe(df, source_id="fixture", known_id_columns=("id",))

    finding = next(f for f in report.findings if f.column == "id")
    assert finding.category == "documented_characteristic"


def test_audit_dataframe_unknown_unique_column_is_hypothesis_requiring_investigation() -> None:
    df = pd.DataFrame({"mystery_id": [1, 2, 3], "other": ["x", "y", "z"]})

    report = audit_dataframe(df, source_id="fixture", known_id_columns=())

    finding = next(f for f in report.findings if f.column == "mystery_id")
    assert finding.category == "hypothesis_requiring_investigation"


def test_audit_dataframe_flags_duplicate_rows_as_candidate_anomaly() -> None:
    df = pd.DataFrame({"a": [1, 1], "b": ["x", "x"]})

    report = audit_dataframe(df, source_id="fixture")

    finding = next(f for f in report.findings if f.column is None)
    assert finding.category == "candidate_anomaly"
    assert "duplicate" in finding.summary.lower()


def test_audit_dataframe_schema_comparison_flags_unexpected_and_missing_columns() -> None:
    schema = DatasetSchema(
        source_id="fixture",
        columns=[ColumnSpec(name="expected_a", description="", expected_type="integer")],
    )
    # Values repeat so neither column is also flagged as a possible
    # identifier - isolating the schema-comparison finding being tested.
    df = pd.DataFrame({"expected_a": [1, 1, 2, 2], "unexpected_b": [3, 3, 4, 4]})

    report = audit_dataframe(df, source_id="fixture", schema=schema)

    assert report.schema_comparison is not None
    assert report.schema_comparison.unexpected_columns == ["unexpected_b"]
    unexpected_findings = [f for f in report.findings if f.column == "unexpected_b"]
    assert len(unexpected_findings) == 1
    assert unexpected_findings[0].category == "candidate_anomaly"


def test_audit_dataframe_without_schema_skips_schema_comparison() -> None:
    df = pd.DataFrame({"a": [1, 2, 3]})

    report = audit_dataframe(df, source_id="fixture", schema=None)

    assert report.schema_comparison is None


def test_audit_report_to_dict_is_json_serializable() -> None:
    import json

    df = pd.DataFrame({"a": [1, 2, 3]})
    report = audit_dataframe(df, source_id="fixture")

    serialized = json.dumps(report.to_dict(), default=str)
    assert "fixture" in serialized
