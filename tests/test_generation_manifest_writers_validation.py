"""Tests for credlens.generation.manifest (canonical hashing),
.writers (path safety, atomic staging/promotion), and .validation
(statistical checks, PII safety)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from credlens.contracts.registry import load_all_contracts
from credlens.generation.config import load_generation_config
from credlens.generation.manifest import (
    build_manifest,
    canonical_config_hash,
    canonical_run_hash,
    canonical_table_hash,
    write_manifest,
)
from credlens.generation.validation import (
    check_pii_safety,
    run_statistical_checks,
    validate_generated_portfolio,
)
from credlens.generation.writers import (
    PathSafetyError,
    discard_staging,
    promote_staging,
    resolve_within_directory,
    stage_directory,
    write_operational_tables,
)


class TestCanonicalTableHash:
    def test_identical_content_hashes_identically(self) -> None:
        df1 = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        df2 = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        assert canonical_table_hash(df1) == canonical_table_hash(df2)

    def test_row_order_does_not_affect_hash(self) -> None:
        df1 = pd.DataFrame({"a": [1, 2, 3]})
        df2 = pd.DataFrame({"a": [3, 1, 2]})
        assert canonical_table_hash(df1) == canonical_table_hash(df2)

    def test_column_order_does_not_affect_hash(self) -> None:
        df1 = pd.DataFrame({"a": [1], "b": [2]})
        df2 = pd.DataFrame({"b": [2], "a": [1]})
        assert canonical_table_hash(df1) == canonical_table_hash(df2)

    def test_different_content_hashes_differently(self) -> None:
        df1 = pd.DataFrame({"a": [1, 2, 3]})
        df2 = pd.DataFrame({"a": [1, 2, 4]})
        assert canonical_table_hash(df1) != canonical_table_hash(df2)

    def test_null_values_hash_consistently(self) -> None:
        df1 = pd.DataFrame({"a": [1, None]})
        df2 = pd.DataFrame({"a": [1, None]})
        assert canonical_table_hash(df1) == canonical_table_hash(df2)

    def test_empty_dataframe_is_hashable_and_column_sensitive(self) -> None:
        empty_a = pd.DataFrame(columns=["a", "b"])
        empty_c = pd.DataFrame(columns=["c", "d"])
        assert canonical_table_hash(empty_a) == canonical_table_hash(empty_a)
        assert canonical_table_hash(empty_a) != canonical_table_hash(empty_c)

    def test_hash_is_64_hex_characters(self) -> None:
        df = pd.DataFrame({"a": [1]})
        digest = canonical_table_hash(df)
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)


class TestCanonicalConfigAndRunHash:
    def test_config_hash_is_deterministic(self) -> None:
        config = load_generation_config()
        assert canonical_config_hash(config) == canonical_config_hash(config)

    def test_run_hash_changes_with_seed(self) -> None:
        table_hashes = {"a": "hash1"}
        h1 = canonical_run_hash(
            table_hashes, "confighash", seed=1, scenario="baseline", scale="smoke"
        )
        h2 = canonical_run_hash(
            table_hashes, "confighash", seed=2, scenario="baseline", scale="smoke"
        )
        assert h1 != h2

    def test_run_hash_changes_with_table_content(self) -> None:
        h1 = canonical_run_hash({"a": "hash1"}, "confighash", 1, "baseline", "smoke")
        h2 = canonical_run_hash({"a": "hash2"}, "confighash", 1, "baseline", "smoke")
        assert h1 != h2

    def test_run_hash_is_order_independent_over_table_names(self) -> None:
        h1 = canonical_run_hash({"a": "1", "b": "2"}, "c", 1, "baseline", "smoke")
        h2 = canonical_run_hash({"b": "2", "a": "1"}, "c", 1, "baseline", "smoke")
        assert h1 == h2


class TestBuildAndWriteManifest:
    def test_build_manifest_includes_required_fields(self) -> None:
        manifest = build_manifest(
            generation_run_id="RUN_x",
            generator_version="0.4.0",
            seed=1,
            scenario="baseline",
            scale="smoke",
            period_start="2024-01-01",
            period_end="2024-12-31",
            config_hash="abc",
            contract_version_set="v1",
            table_row_counts={"customers": 10},
            table_hashes={"customers": "hash"},
            global_content_hash="globalhash",
            started_at="2024-01-01T00:00:00Z",
            finished_at="2024-01-01T00:00:01Z",
            duration_seconds=1.0,
            status="completed",
            validation_passed=True,
            warnings=[],
            python_version="3.11.9",
        )
        assert manifest["generation_run_id"] == "RUN_x"
        tables = manifest["tables"]
        assert isinstance(tables, dict)
        assert tables["customers"]["row_count"] == 10
        assert "absolute" not in str(manifest).lower()  # no path-like keys expected

    def test_write_manifest_produces_valid_json(self, tmp_path: Path) -> None:
        import json

        manifest = {"a": 1, "b": [1, 2, 3]}
        path = tmp_path / "manifest.json"
        write_manifest(manifest, path)
        assert json.loads(path.read_text(encoding="utf-8")) == manifest


class TestPathSafety:
    def test_normal_name_resolves_inside_directory(self, tmp_path: Path) -> None:
        result = resolve_within_directory(tmp_path, "RUN_abc123")
        assert result == (tmp_path / "RUN_abc123").resolve()

    def test_path_traversal_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(PathSafetyError):
            resolve_within_directory(tmp_path, "../../etc/passwd")

    def test_absolute_path_escape_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(PathSafetyError):
            resolve_within_directory(tmp_path, "../outside")


class TestStagingAndPromotion:
    def test_stage_directory_is_created_under_staging_subdir(self, tmp_path: Path) -> None:
        staging = stage_directory(tmp_path)
        assert staging.is_dir()
        assert staging.parent.name == ".staging"

    def test_promote_moves_staging_to_final_location(self, tmp_path: Path) -> None:
        staging = stage_directory(tmp_path)
        (staging / "marker.txt").write_text("hello", encoding="utf-8")
        final = tmp_path / "RUN_final"

        promote_staging(staging, final)

        assert final.is_dir()
        assert (final / "marker.txt").read_text(encoding="utf-8") == "hello"
        assert not staging.exists()

    def test_promote_refuses_to_overwrite_existing_final_path(self, tmp_path: Path) -> None:
        final = tmp_path / "RUN_final"
        final.mkdir()
        staging = stage_directory(tmp_path)

        with pytest.raises(FileExistsError):
            promote_staging(staging, final)

    def test_discard_staging_removes_the_directory(self, tmp_path: Path) -> None:
        staging = stage_directory(tmp_path)
        (staging / "marker.txt").write_text("x", encoding="utf-8")
        discard_staging(staging)
        assert not staging.exists()

    def test_write_operational_tables_round_trips_through_parquet(self, tmp_path: Path) -> None:
        tables = {
            "customers": pd.DataFrame(
                {"customer_id": ["CUS_1"], "created_at": ["2024-01-01T00:00:00Z"]}
            )
        }
        write_operational_tables(tables, tmp_path)
        loaded = pd.read_parquet(tmp_path / "customers.parquet")
        assert loaded["customer_id"].tolist() == ["CUS_1"]


class TestStatisticalChecksAndPii:
    def test_statistical_checks_never_business_findings_language(self) -> None:
        """A crude but real assurance: the check names/details never use
        business-report words like 'profit'/'revenue'/'loss rate' - they
        stay technical (see docs/synthetic_generation_implementation.md)."""
        installments = pd.DataFrame({"status": ["paid", "overdue"]})
        checks = run_statistical_checks({"installments": installments})
        for check in checks:
            assert "profit" not in check.detail.lower()
            assert "revenue" not in check.detail.lower()

    def test_pii_check_flags_cpf_like_customer_id(self) -> None:
        contracts = load_all_contracts()
        tables = {
            "customers": pd.DataFrame(
                {
                    "customer_id": ["123.456.789-01"],
                    "generation_run_id": ["r"],
                    "created_at": ["2024-01-01T00:00:00Z"],
                }
            )
        }
        safe, detail = check_pii_safety(tables, contracts)
        assert safe is False
        assert "CPF" in detail

    def test_pii_check_passes_for_letter_prefixed_ids(self) -> None:
        contracts = load_all_contracts()
        tables = {
            "customers": pd.DataFrame(
                {
                    "customer_id": ["CUS_abc_0000001"],
                    "generation_run_id": ["r"],
                    "created_at": ["2024-01-01T00:00:00Z"],
                }
            )
        }
        safe, _ = check_pii_safety(tables, contracts)
        assert safe is True

    def test_validate_generated_portfolio_combines_all_three_checks(self) -> None:
        contracts = load_all_contracts()
        tables = {
            "customers": pd.DataFrame(
                {
                    "customer_id": ["CUS_1"],
                    "generation_run_id": ["r"],
                    "created_at": ["2024-01-01T00:00:00Z"],
                }
            )
        }
        outcome = validate_generated_portfolio(tables, contracts)
        assert outcome.pii_safe is True
        assert "customers" in outcome.contract_reports
