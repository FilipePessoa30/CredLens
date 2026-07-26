"""Tests for credlens.analysis.insights (Phase 7 gate D): every insight
must be generated from a real analysis output (never hand-typed numbers),
carry every required field, and correctly exclude unsupported/hypothesis
statements and insufficient-sample segments from "executive-ready"."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.analysis.insights import (
    Insight,
    InsightsGenerationError,
    content_fingerprint,
    generate_insights,
    is_executive_ready,
    write_insights_registry,
)
from credlens.analysis.runner import run_analysis
from credlens.generation.suite import generate_suite
from credlens.generation.testing_support import (
    isolated_manifest_dir,
    isolated_output_dirs,
    safe_rmtree,
)
from credlens.warehouse.build import _rmtree_with_retry, build_dir_for, run_build

_SEED = 703_509
_BUILD_ID = "BUILD_pytest_analysis_insights"

_REQUIRED_FIELDS = (
    "insight_id",
    "question_id",
    "title",
    "statement",
    "statement_type",
    "baseline_value",
    "compared_value",
    "delta",
    "unit",
    "period",
    "grain",
    "filters",
    "scenario",
    "seed_or_seeds",
    "sample_size",
    "sample_classification",
    "dbt_model",
    "query",
    "evidence_table",
    "figure",
    "build_id",
    "warehouse_fingerprint",
    "analysis_id",
    "provenance_classification",
    "limitation",
    "validation_status",
)


@pytest.fixture(scope="module")
def isolated_suite(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path, Path]]:
    tmp_path = tmp_path_factory.mktemp("analysis_insights")
    operational_dir, truth_dir = isolated_output_dirs(tmp_path)
    manifest_dir = isolated_manifest_dir(tmp_path)
    outcome = generate_suite(
        scale_name="smoke",
        seed=_SEED,
        force=True,
        output_dirs=(operational_dir, truth_dir),
        manifest_dir=manifest_dir,
    )
    yield outcome.suite_id, operational_dir, manifest_dir
    safe_rmtree(tmp_path, allowed_root=tmp_path)


@pytest.fixture(scope="module")
def analysis_output(
    isolated_suite: tuple[str, Path, Path], tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Path]:
    suite_id, operational_dir, manifest_dir = isolated_suite
    manifest = run_build(
        suite_id=suite_id,
        build_id=_BUILD_ID,
        force=True,
        operational_root=operational_dir,
        manifest_dir=manifest_dir,
    )
    assert manifest.final_status == "success"
    output_dir = tmp_path_factory.mktemp("insights_report")
    run_analysis(build_id=manifest.build_id, output_dir=output_dir, include_benchmark=False)
    yield output_dir
    build_dir = build_dir_for(_BUILD_ID)
    if build_dir.exists():
        try:
            _rmtree_with_retry(build_dir)
        except PermissionError:
            shutil.rmtree(build_dir, ignore_errors=True)


class TestGenerateInsights:
    def test_raises_when_manifest_is_missing(self, tmp_path: Path) -> None:
        with pytest.raises(InsightsGenerationError):
            generate_insights(tmp_path)

    def test_generates_at_least_one_insight_per_required_category(
        self, analysis_output: Path
    ) -> None:
        insights = generate_insights(analysis_output)
        titles = " ".join(i.title.lower() for i in insights)
        for keyword in (
            "funnel",
            "outstanding balance",
            "par30",
            "vintage",
            "roll-forward",
            "cure rate",
            "redefault",
            "write-off",
            "recovery",
        ):
            assert keyword in titles, f"no insight covers {keyword!r}"

    def test_scenario_comparisons_present_for_expansion_and_tightening(
        self, analysis_output: Path
    ) -> None:
        insights = generate_insights(analysis_output)
        scenario_titles = {i.scenario for i in insights if i.scenario}
        assert "policy_expansion" in scenario_titles
        assert "policy_tightening" in scenario_titles
        assert "collections_change" in scenario_titles

    def test_every_insight_has_every_required_field(self, analysis_output: Path) -> None:
        insights = generate_insights(analysis_output)
        for insight in insights:
            d = insight.to_dict()
            for field_name in _REQUIRED_FIELDS:
                assert field_name in d, f"{insight.insight_id} missing {field_name}"

    def test_every_insight_traces_to_the_same_build(self, analysis_output: Path) -> None:
        manifest = json.loads((analysis_output / "manifest.json").read_text(encoding="utf-8"))
        insights = generate_insights(analysis_output)
        for insight in insights:
            assert insight.build_id == manifest["build_id"]
            assert insight.warehouse_fingerprint == manifest["warehouse_fingerprint"]
            assert insight.analysis_id == manifest["analysis_id"]

    def test_unsupported_example_is_present_and_flagged(self, analysis_output: Path) -> None:
        insights = generate_insights(analysis_output)
        unsupported = [i for i in insights if i.statement_type == "unsupported"]
        assert len(unsupported) >= 1
        for insight in unsupported:
            assert is_executive_ready(insight) is False

    def test_numeric_values_are_not_hand_typed_but_match_the_table(
        self, analysis_output: Path
    ) -> None:
        import pandas as pd

        insights = generate_insights(analysis_output)
        funnel_insight = next(i for i in insights if i.insight_id == "INS-FUN-001")
        funnel_df = pd.read_csv(analysis_output / "tables" / "funnel_monthly.csv")
        baseline = funnel_df[funnel_df["scenario"] == "baseline"]
        assert funnel_insight.baseline_value == float(baseline["applications_submitted"].sum())
        assert funnel_insight.compared_value == float(baseline["booked_count"].sum())


class TestIsExecutiveReady:
    def _make_insight(self, **overrides: object) -> Insight:
        base: dict[str, object] = {
            "insight_id": "INS-TEST-001",
            "question_id": None,
            "title": "t",
            "statement_en": "s",
            "statement_pt": "s",
            "statement_type": "observed_synthetic_result",
            "baseline_value": None,
            "compared_value": None,
            "delta": None,
            "unit": "n/a",
            "period": "n/a",
            "grain": "n/a",
            "filters": {},
            "scenario": None,
            "seed_or_seeds": "n/a",
            "sample_size": None,
            "sample_classification": None,
            "dbt_model": None,
            "query_function": "n/a",
            "evidence_table": "n/a",
            "figure": None,
            "build_id": "BUILD_x",
            "warehouse_fingerprint": "fp",
            "analysis_id": "ANALYSIS_x",
            "provenance_classification": "synthetic_operational",
            "limitation": "n/a",
            "validation_status": "validated",
        }
        base.update(overrides)
        return Insight(**base)  # type: ignore[arg-type]

    def test_unsupported_is_never_executive_ready(self) -> None:
        insight = self._make_insight(statement_type="unsupported")
        assert is_executive_ready(insight) is False

    def test_hypothesis_is_never_executive_ready(self) -> None:
        insight = self._make_insight(statement_type="hypothesis")
        assert is_executive_ready(insight) is False

    def test_insufficient_sample_is_never_executive_ready(self) -> None:
        insight = self._make_insight(sample_classification="insufficient")
        assert is_executive_ready(insight) is False

    def test_adequate_observed_result_is_executive_ready(self) -> None:
        insight = self._make_insight(sample_classification="adequate")
        assert is_executive_ready(insight) is True

    def test_limited_sample_may_still_be_executive_ready(self) -> None:
        insight = self._make_insight(sample_classification="limited")
        assert is_executive_ready(insight) is True


class TestContentFingerprint:
    """Phase 7 gate E regression test: insights.yml embeds a fresh
    analysis_id (execution metadata) on every run - the raw file's byte
    hash would spuriously differ across two otherwise-identical runs of
    the exact same build. content_fingerprint() must be stable despite
    that, by excluding analysis_id."""

    def test_fingerprint_is_stable_across_different_analysis_ids(
        self, analysis_output: Path
    ) -> None:
        import dataclasses

        insights_a = generate_insights(analysis_output)
        insights_b = [
            dataclasses.replace(i, analysis_id="ANALYSIS_a_totally_different_id")
            for i in insights_a
        ]
        assert content_fingerprint(insights_a) == content_fingerprint(insights_b)

    def test_fingerprint_changes_if_a_real_value_changes(self, analysis_output: Path) -> None:
        import dataclasses

        insights_a = generate_insights(analysis_output)
        insights_b = [dataclasses.replace(i, compared_value=999999.0) for i in insights_a]
        assert content_fingerprint(insights_a) != content_fingerprint(insights_b)

    def test_two_independent_generations_from_the_same_build_match(
        self, analysis_output: Path
    ) -> None:
        insights_first = generate_insights(analysis_output)
        insights_second = generate_insights(analysis_output)
        assert content_fingerprint(insights_first) == content_fingerprint(insights_second)


class TestWriteInsightsRegistry:
    def test_writes_valid_yaml_with_every_insight(
        self, analysis_output: Path, tmp_path: Path
    ) -> None:
        import yaml

        insights = generate_insights(analysis_output)
        out_path = tmp_path / "insights.yml"
        write_insights_registry(insights, out_path)
        loaded = yaml.safe_load(out_path.read_text(encoding="utf-8"))
        assert loaded["count"] == len(insights)
        assert len(loaded["insights"]) == len(insights)
