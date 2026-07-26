"""Tests for credlens.analysis.provenance (Phase 6 section 18): the
analysis manifest must record real file hashes (not placeholders), refuse
silently when a table/figure is missing, and round-trip through JSON. No
warehouse needed - a BuildManifest is constructed directly with plausible
field values, since new_manifest() only reads plain fields off it."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from credlens.analysis.provenance import (
    finalize,
    new_manifest,
    record_figure,
    record_report,
    record_table,
)
from credlens.warehouse.build import BuildManifest


def _fake_build_manifest() -> BuildManifest:
    return BuildManifest(
        build_id="BUILD_fake_for_provenance_test",
        db_path="data/warehouse/BUILD_fake_for_provenance_test/warehouse.duckdb",
        run_id=None,
        suite_id="SUITE_smoke_123456",
        included_run_ids=["RUN_baseline_smoke_123456", "RUN_policy_expansion_smoke_123456"],
        code_version="0.7.0",
        dbt_version="1.8.0",
        duckdb_version="1.0.0",
        sources=[
            {
                "run_id": "RUN_baseline_smoke_123456",
                "global_content_hash": "abc123",
                "contract_version_set": "phase5-v1",
                "generator_version": "0.5.0",
            },
            {
                "run_id": "RUN_policy_expansion_smoke_123456",
                "global_content_hash": "def456",
                "contract_version_set": "phase5-v1",
                "generator_version": "0.5.0",
            },
        ],
        raw_row_counts={},
        model_row_counts={},
        test_results={"passed": 135, "failed": 0, "errored": 0, "skipped": 0, "failures": []},
        step_durations={"total": 12.3},
        analytical_fingerprint="fake-fingerprint-0000",
        final_status="success",
        built_at="2026-07-26T00:00:00Z",
    )


class TestNewManifest:
    def test_carries_over_build_identity_fields(self) -> None:
        build = _fake_build_manifest()
        m = new_manifest(build, "ANALYSIS_test_0001")
        assert m.analysis_id == "ANALYSIS_test_0001"
        assert m.build_id == build.build_id
        assert m.warehouse_fingerprint == build.analytical_fingerprint
        assert m.suite_id == build.suite_id
        assert m.run_ids == build.included_run_ids
        assert m.final_status == "running"
        assert m.finished_at is None
        assert m.queries_executed == []
        assert m.tables_written == {}
        assert m.figures_written == {}
        assert m.warnings == []
        assert m.parameters == {}

    def test_parameters_are_stored_verbatim_when_given(self) -> None:
        build = _fake_build_manifest()
        params = {"include_benchmark": False, "include_multiseed": True, "multiseed_seeds": 7}
        m = new_manifest(build, "ANALYSIS_test_0001b", params)
        assert m.parameters == params
        # A defensive copy, not the same dict object.
        params["include_benchmark"] = True
        assert m.parameters["include_benchmark"] is False

    def test_source_hashes_keyed_by_run_id(self) -> None:
        build = _fake_build_manifest()
        m = new_manifest(build, "ANALYSIS_test_0002")
        assert m.source_hashes == {
            "RUN_baseline_smoke_123456": "abc123",
            "RUN_policy_expansion_smoke_123456": "def456",
        }

    def test_contract_version_sets_deduplicated_and_sorted(self) -> None:
        build = _fake_build_manifest()
        m = new_manifest(build, "ANALYSIS_test_0003")
        assert m.contract_version_sets == ["phase5-v1"]


class TestRecordTableAndFigure:
    def test_record_table_hashes_real_file_content(self, tmp_path: Path) -> None:
        build = _fake_build_manifest()
        m = new_manifest(build, "ANALYSIS_test_0004")
        table_path = tmp_path / "funnel_monthly.csv"
        table_path.write_text("a,b\n1,2\n", encoding="utf-8")

        record_table(m, "funnel_monthly", table_path)

        expected = hashlib.sha256(table_path.read_bytes()).hexdigest()
        assert m.tables_written["funnel_monthly"] == expected

    def test_record_table_missing_file_records_missing(self, tmp_path: Path) -> None:
        build = _fake_build_manifest()
        m = new_manifest(build, "ANALYSIS_test_0005")
        record_table(m, "does_not_exist", tmp_path / "nope.csv")
        assert m.tables_written["does_not_exist"] == "missing"

    def test_record_figure_hashes_real_file_content(self, tmp_path: Path) -> None:
        build = _fake_build_manifest()
        m = new_manifest(build, "ANALYSIS_test_0006")
        figure_path = tmp_path / "chart.png"
        figure_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-but-nonempty")

        record_figure(m, "chart", figure_path)

        expected = hashlib.sha256(figure_path.read_bytes()).hexdigest()
        assert m.figures_written["chart"] == expected

    def test_record_report_hashes_real_file_content(self, tmp_path: Path) -> None:
        """Phase 7 gate E: reports (executive/technical summaries, the
        insights registry) get the SAME content-hash treatment
        tables/figures already have."""
        build = _fake_build_manifest()
        m = new_manifest(build, "ANALYSIS_test_0004b")
        report_path = tmp_path / "executive_summary.md"
        report_path.write_text("# Executive Summary\n", encoding="utf-8")

        record_report(m, "executive_summary_en", report_path)

        expected = hashlib.sha256(report_path.read_bytes()).hexdigest()
        assert m.reports_written["executive_summary_en"] == expected

    def test_record_report_missing_file_records_missing(self, tmp_path: Path) -> None:
        build = _fake_build_manifest()
        m = new_manifest(build, "ANALYSIS_test_0004c")
        record_report(m, "does_not_exist", tmp_path / "nope.md")
        assert m.reports_written["does_not_exist"] == "missing"

    def test_two_different_files_hash_differently(self, tmp_path: Path) -> None:
        build = _fake_build_manifest()
        m = new_manifest(build, "ANALYSIS_test_0007")
        p1, p2 = tmp_path / "a.csv", tmp_path / "b.csv"
        p1.write_text("content-a", encoding="utf-8")
        p2.write_text("content-b", encoding="utf-8")
        record_table(m, "a", p1)
        record_table(m, "b", p2)
        assert m.tables_written["a"] != m.tables_written["b"]


class TestFinalize:
    def test_sets_finished_at_and_status(self) -> None:
        build = _fake_build_manifest()
        m = new_manifest(build, "ANALYSIS_test_0008")
        assert m.finished_at is None
        finalize(m, status="success")
        assert m.finished_at is not None
        assert m.final_status == "success"


class TestManifestSerialization:
    def test_to_dict_contains_every_declared_field(self) -> None:
        build = _fake_build_manifest()
        m = new_manifest(build, "ANALYSIS_test_0009")
        d = m.to_dict()
        for field_name in (
            "analysis_id",
            "build_id",
            "warehouse_fingerprint",
            "suite_id",
            "run_ids",
            "source_hashes",
            "generator_version",
            "contract_version_sets",
            "package_version",
            "dbt_version",
            "duckdb_version",
            "python_version",
            "started_at",
            "finished_at",
            "queries_executed",
            "tables_written",
            "figures_written",
            "warnings",
            "final_status",
            "parameters",
        ):
            assert field_name in d

    def test_write_produces_valid_json_matching_to_dict(self, tmp_path: Path) -> None:
        build = _fake_build_manifest()
        m = new_manifest(build, "ANALYSIS_test_0010")
        finalize(m, status="success")
        out_path = tmp_path / "manifest.json"

        m.write(out_path)

        loaded = json.loads(out_path.read_text(encoding="utf-8"))
        assert loaded == m.to_dict()

    def test_write_creates_parent_directories(self, tmp_path: Path) -> None:
        build = _fake_build_manifest()
        m = new_manifest(build, "ANALYSIS_test_0011")
        out_path = tmp_path / "nested" / "dir" / "manifest.json"
        m.write(out_path)
        assert out_path.is_file()
