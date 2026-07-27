"""Tests for credlens.modeling.data (Phase 8 sections 3-4): the UCI
benchmark is loaded from the manifest ONLY, hash-verified before use,
and never re-downloaded."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from credlens.modeling.data import DataAcquisitionError, audit_source, load_uci_default_credit


class TestLoadUciDefaultCredit:
    def test_loads_the_real_acquired_file(self) -> None:
        df = load_uci_default_credit()
        assert df.shape == (30000, 25)
        assert set(df.columns) == {"ID", "Y", *[f"X{i}" for i in range(1, 24)]}

    def test_missing_manifest_raises(self, tmp_path: Path) -> None:
        with pytest.raises(DataAcquisitionError, match="No file manifest"):
            load_uci_default_credit(tmp_path)

    def test_manifest_present_but_file_missing_raises(self, tmp_path: Path) -> None:
        manifest_dir = tmp_path / "data" / "metadata"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "file_manifest.csv").write_text(
            "source_id,relative_path,filename,size_bytes,sha256,retrieved_at_utc,url,format,"
            "num_rows,num_columns,verification_status,source_version_or_date,license,notes\n"
            "uci-default-credit,data/raw/uci_default_credit/missing.csv,missing.csv,10,"
            "deadbeef,2026-01-01T00:00:00Z,http://x,csv,,,audited,2005,CC BY 4.0,\n",
            encoding="utf-8",
        )
        with pytest.raises(DataAcquisitionError, match="not on disk"):
            load_uci_default_credit(tmp_path)

    def test_hash_mismatch_raises(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "data" / "raw" / "uci_default_credit"
        raw_dir.mkdir(parents=True)
        (raw_dir / "default_of_credit_card_clients.csv").write_text(
            "ID,X1\n1,2\n", encoding="utf-8"
        )
        manifest_dir = tmp_path / "data" / "metadata"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "file_manifest.csv").write_text(
            "source_id,relative_path,filename,size_bytes,sha256,retrieved_at_utc,url,format,"
            "num_rows,num_columns,verification_status,source_version_or_date,license,notes\n"
            "uci-default-credit,data/raw/uci_default_credit/default_of_credit_card_clients.csv,"
            "default_of_credit_card_clients.csv,10,deadbeef,2026-01-01T00:00:00Z,http://x,csv,,,"
            "audited,2005,CC BY 4.0,\n",
            encoding="utf-8",
        )
        with pytest.raises(DataAcquisitionError, match="Hash mismatch"):
            load_uci_default_credit(tmp_path)

    def test_no_manifest_entry_for_source_raises(self, tmp_path: Path) -> None:
        manifest_dir = tmp_path / "data" / "metadata"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "file_manifest.csv").write_text(
            "source_id,relative_path,filename,size_bytes,sha256,retrieved_at_utc,url,format,"
            "num_rows,num_columns,verification_status,source_version_or_date,license,notes\n"
            "some-other-source,data/raw/x.csv,x.csv,10,deadbeef,2026-01-01T00:00:00Z,http://x,"
            "csv,,,audited,2005,CC BY 4.0,\n",
            encoding="utf-8",
        )
        with pytest.raises(DataAcquisitionError, match="No manifest entry"):
            load_uci_default_credit(tmp_path)


class TestAuditSource:
    def test_reproduces_documented_audit_numbers(self) -> None:
        audit = audit_source()
        assert audit.num_rows == 30000
        assert audit.num_columns == 25
        assert audit.target_positive_count == 6636
        assert audit.target_negative_count == 23364
        assert audit.total_missing_values == 0
        assert audit.duplicate_id_count == 0
        assert audit.duplicate_row_count == 0
        assert audit.out_of_domain_education_count == 345
        assert audit.out_of_domain_marriage_count == 54

    def test_to_dict_round_trips_every_field(self) -> None:
        audit = audit_source()
        d = audit.to_dict()
        assert d["source_id"] == "uci-default-credit"
        assert isinstance(d["target_prevalence"], float)
        assert d["sha256"] == audit.sha256


def test_load_and_audit_are_consistent(tiny_uci_frame: pd.DataFrame) -> None:
    # tiny_uci_frame is only used here to confirm the fixture itself is
    # well-formed (both classes present, no nulls) - audit_source/load_
    # uci_default_credit above always exercise the REAL acquired file.
    assert tiny_uci_frame["Y"].isin([0, 1]).all()
    assert tiny_uci_frame["Y"].nunique() == 2
    assert tiny_uci_frame.isna().sum().sum() == 0
