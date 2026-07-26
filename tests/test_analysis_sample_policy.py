"""Tests for credlens.analysis.sample_policy (Phase 7 gate B): the
three-tier minimum-sample classification (insufficient / limited /
adequate) that replaces Phase 6's flat MIN_SEGMENT_OBSERVATIONS = 10
cutoff, its exact boundaries (29/30/99/100), and that ranking/
recommendation is suppressed for insufficient segments end-to-end
through credlens.analysis.metrics and credlens.analysis.scenarios."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from credlens.analysis.sample_policy import (
    CLASSIFICATION_LABELS,
    DEFAULT_POLICY,
    SamplePolicy,
    SamplePolicyError,
    classify_sample_size,
    combine_classifications,
    is_reportable,
    load_sample_policy,
)


class TestSamplePolicyBoundaries:
    """The exact boundaries the spec calls out: 29, 30, 99, 100."""

    @pytest.mark.parametrize(
        ("n", "expected"),
        [
            (0, "insufficient"),
            (1, "insufficient"),
            (29, "insufficient"),
            (30, "limited"),
            (31, "limited"),
            (99, "limited"),
            (100, "adequate"),
            (101, "adequate"),
            (10_000, "adequate"),
        ],
    )
    def test_default_policy_boundaries(self, n: int, expected: str) -> None:
        assert DEFAULT_POLICY.classify(n) == expected

    def test_boundaries_are_configurable(self) -> None:
        policy = SamplePolicy(insufficient_below=5, limited_below=10)
        assert policy.classify(4) == "insufficient"
        assert policy.classify(5) == "limited"
        assert policy.classify(9) == "limited"
        assert policy.classify(10) == "adequate"


class TestSamplePolicyValidation:
    def test_rejects_non_positive_thresholds(self) -> None:
        with pytest.raises(SamplePolicyError):
            SamplePolicy(insufficient_below=0, limited_below=100)

    def test_rejects_insufficient_below_not_less_than_limited_below(self) -> None:
        with pytest.raises(SamplePolicyError):
            SamplePolicy(insufficient_below=100, limited_below=100)
        with pytest.raises(SamplePolicyError):
            SamplePolicy(insufficient_below=101, limited_below=100)


class TestLoadSamplePolicy:
    def test_loads_the_versioned_policy_file(self) -> None:
        policy = load_sample_policy(Path("analysis/specifications/segmentation_policy.yaml"))
        assert policy.insufficient_below == 30
        assert policy.limited_below == 100

    def test_falls_back_to_default_when_file_absent(self, tmp_path: Path) -> None:
        policy = load_sample_policy(tmp_path / "does_not_exist.yaml")
        assert policy == DEFAULT_POLICY

    def test_malformed_file_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("not_segmentation: {}\n", encoding="utf-8")
        with pytest.raises(SamplePolicyError):
            load_sample_policy(bad)

    def test_missing_key_raises(self, tmp_path: Path) -> None:
        incomplete = tmp_path / "incomplete.yaml"
        incomplete.write_text("segmentation:\n  insufficient_below: 30\n", encoding="utf-8")
        with pytest.raises(SamplePolicyError, match="missing key"):
            load_sample_policy(incomplete)


class TestSamplePolicyToDict:
    def test_round_trips_both_thresholds(self) -> None:
        policy = SamplePolicy(insufficient_below=30, limited_below=100)
        assert policy.to_dict() == {"insufficient_below": 30, "limited_below": 100}


class TestClassifySampleSize:
    def test_uses_injected_policy(self) -> None:
        policy = SamplePolicy(insufficient_below=2, limited_below=4)
        assert classify_sample_size(1, policy) == "insufficient"
        assert classify_sample_size(2, policy) == "limited"
        assert classify_sample_size(4, policy) == "adequate"


class TestCombineClassifications:
    def test_worst_of_several_counts_wins(self) -> None:
        policy = SamplePolicy(insufficient_below=30, limited_below=100)
        assert combine_classifications(500, 5, policy=policy) == "insufficient"
        assert combine_classifications(500, 50, policy=policy) == "limited"
        assert combine_classifications(500, 200, policy=policy) == "adequate"

    def test_requires_at_least_one_count(self) -> None:
        with pytest.raises(ValueError):
            combine_classifications()


class TestIsReportable:
    def test_only_insufficient_is_not_reportable(self) -> None:
        assert is_reportable("adequate") is True
        assert is_reportable("limited") is True
        assert is_reportable("insufficient") is False


class TestClassificationLabelsAreNotStatisticalClaims:
    def test_no_label_claims_a_statistical_guarantee(self) -> None:
        forbidden = (
            "confidence interval",
            "statistically significant",
            "p-value",
            "margin of error",
        )
        for label in CLASSIFICATION_LABELS.values():
            lowered = label.lower()
            assert not any(term in lowered for term in forbidden)


class TestRankingSuppressionEndToEnd:
    """Gate B section 5.1: insufficient groups must never be ranked or
    highlighted as best/worst - proven directly against the suppression
    helper used by report/dashboard ranking code (Phase 7 gate D reuses
    the same helper - see analysis/robustness.py and dashboard/components.py)."""

    def test_rankable_subset_excludes_insufficient_rows(self) -> None:
        df = pd.DataFrame(
            {
                "segment": ["a", "b", "c", "d"],
                "count": [5, 40, 150, 20],
                "rate": [0.9, 0.5, 0.3, 0.99],
            }
        )
        df["sample_classification"] = df["count"].map(classify_sample_size)
        rankable = df[df["sample_classification"].map(is_reportable)]
        assert set(rankable["segment"]) == {"b", "c"}
        # The best/worst by rate must come only from the rankable subset -
        # segment 'd' has the highest rate (0.99) but is insufficient
        # (count=20 < 30) and must never surface as "best".
        best_segment = rankable.loc[rankable["rate"].idxmax(), "segment"]
        assert best_segment != "d"

    def test_insufficient_rows_stay_visible_for_audit_but_unranked(self) -> None:
        df = pd.DataFrame({"segment": ["tiny"], "count": [3], "rate": [1.0]})
        df["sample_classification"] = df["count"].map(classify_sample_size)
        # Still present in the table (audit-visible)...
        assert "tiny" in set(df["segment"])
        # ...but excluded from anything that would rank/recommend it.
        classification = str(df.loc[0, "sample_classification"])
        assert classification == "insufficient"
        assert not is_reportable(classification)  # type: ignore[arg-type]
