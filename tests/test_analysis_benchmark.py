"""Tests for credlens.analysis.benchmark (Phase 6 section 14): profiles
the already-acquired public sources, kept strictly separate from any
synthetic build. No warehouse needed - these tests read the real acquired
files under data/raw/ via data/metadata/file_manifest.csv."""

from __future__ import annotations

from pathlib import Path

from credlens.analysis.benchmark import _SOURCE_CONTEXT, BenchmarkProfile, profile_public_sources


class TestProfilePublicSources:
    def test_returns_a_profile_for_every_known_acquired_source(self) -> None:
        profiles = profile_public_sources()
        assert profiles, "expected at least one already-acquired public source"
        source_ids = {p.source_id for p in profiles}
        # Every profile must come from a documented context, never a bare id.
        assert source_ids.issubset(set(_SOURCE_CONTEXT.keys()))

    def test_every_profile_has_positive_rows_and_columns(self) -> None:
        for p in profile_public_sources():
            assert p.num_rows > 0
            assert p.num_columns > 0

    def test_every_profile_carries_its_own_documented_context(self) -> None:
        for p in profile_public_sources():
            assert p.context, (
                f"{p.source_id} has no context - never treat a public source as unlabeled"
            )
            assert "population" in p.context
            assert "period" in p.context

    def test_missing_manifest_returns_empty_list_not_an_error(self, tmp_path: Path) -> None:
        # An empty, isolated repo_root has no data/metadata/file_manifest.csv -
        # the benchmark appendix must degrade to "not included", never raise.
        profiles = profile_public_sources(repo_root=tmp_path)
        assert profiles == []

    def test_bcb_series_are_never_mixed_with_customer_credit_datasets(self) -> None:
        """BCB SGS series are aggregate macro time series, not
        labeled-credit datasets - their context must say so explicitly,
        never imply a target/label the way UCI/South German Credit do."""
        for p in profile_public_sources():
            if p.source_id.startswith("bcb-sgs-"):
                assert "not a labeled credit dataset" in p.context.get("target", "")


class TestBenchmarkProfileToDict:
    def test_to_dict_round_trips_every_field(self) -> None:
        profile = BenchmarkProfile(
            source_id="fake-source",
            num_rows=10,
            num_columns=2,
            missing_value_findings=0,
            domain_findings=1,
            context={"population": "test", "period": "2020"},
        )
        d = profile.to_dict()
        assert d == {
            "source_id": "fake-source",
            "num_rows": 10,
            "num_columns": 2,
            "missing_value_findings": 0,
            "domain_findings": 1,
            "context": {"population": "test", "period": "2020"},
        }


class TestLoaderRobustness:
    def test_unrecognized_source_id_is_silently_skipped(self, tmp_path: Path) -> None:
        """An acquired-but-unrecognized source (no loader registered) must
        never crash the appendix - it is simply omitted."""
        from credlens.data.manifest import write_manifest
        from credlens.data.models import ManifestEntry

        metadata_dir = tmp_path / "data" / "metadata"
        manifest_path = metadata_dir / "file_manifest.csv"

        entry = ManifestEntry(
            source_id="some-unregistered-source",
            relative_path="data/raw/whatever/whatever.csv",
            filename="whatever.csv",
            size_bytes=0,
            sha256="0" * 64,
            retrieved_at_utc="2026-01-01T00:00:00Z",
            url="https://example.invalid/whatever.csv",
            format="csv",
            num_rows=None,
            num_columns=None,
            verification_status="verified",
            source_version_or_date="2026",
            license="CC0",
            notes="",
        )
        write_manifest([entry], manifest_path)

        profiles = profile_public_sources(repo_root=tmp_path)
        assert profiles == []
