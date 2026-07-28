"""Tests for credlens.modeling.input_contract (Phase 9 section 12) -
strict mode blocks batch-level violations and quarantines row-level
ones; audit mode never blocks, only profiles.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from credlens.modeling.input_contract import (
    InputContractError,
    clean_rows,
    validate_input_contract,
    write_quarantine,
)


def _valid_batch(n: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    data = {"ID": np.arange(1, n + 1)}
    for i in range(1, 24):
        if i in (6, 7, 8, 9, 10, 11):
            data[f"X{i}"] = rng.integers(-2, 3, size=n)
        else:
            data[f"X{i}"] = rng.integers(0, 10000, size=n)
    return pd.DataFrame(data)


class TestSchemaViolations:
    def test_missing_column_raises_in_strict_mode(self) -> None:
        batch = _valid_batch().drop(columns=["X6"])
        with pytest.raises(InputContractError):
            validate_input_contract(batch, "strict")

    def test_missing_column_is_profiled_in_audit_mode(self) -> None:
        batch = _valid_batch().drop(columns=["X6"])
        report = validate_input_contract(batch, "audit")
        assert report.has_batch_level_violation
        assert report.n_valid_rows == 0

    def test_extra_column_raises_in_strict_mode(self) -> None:
        batch = _valid_batch()
        batch["BOGUS"] = 1
        with pytest.raises(InputContractError):
            validate_input_contract(batch, "strict")

    def test_y_column_is_tolerated(self) -> None:
        batch = _valid_batch()
        batch["Y"] = 0
        report = validate_input_contract(batch, "strict")
        assert not report.has_batch_level_violation

    def test_wrong_dtype_raises_in_strict_mode(self) -> None:
        batch = _valid_batch()
        batch["X1"] = batch["X1"].astype(object)
        batch.loc[batch.index[0], "X1"] = "not_a_number"
        with pytest.raises(InputContractError):
            validate_input_contract(batch, "strict")

    def test_column_reorder_does_not_raise(self) -> None:
        batch = _valid_batch()
        reordered = batch[list(reversed(batch.columns))]
        report = validate_input_contract(reordered, "strict")
        assert not report.has_batch_level_violation


class TestRowLevelViolations:
    def test_duplicate_id_is_quarantined(self) -> None:
        batch = _valid_batch(5)
        batch.loc[batch.index[-1], "ID"] = batch.loc[batch.index[0], "ID"]
        report = validate_input_contract(batch, "strict")
        assert report.n_quarantined_rows == 1
        assert report.n_valid_rows == 4

    def test_non_finite_value_is_quarantined(self) -> None:
        batch = _valid_batch(5)
        batch.loc[batch.index[0], "X12"] = np.nan
        report = validate_input_contract(batch, "strict")
        assert report.n_quarantined_rows == 1

    def test_out_of_domain_delinquency_code_is_quarantined(self) -> None:
        batch = _valid_batch(5)
        batch.loc[batch.index[0], "X6"] = 15
        report = validate_input_contract(batch, "strict")
        assert report.n_quarantined_rows == 1
        assert report.row_level_violations[0].violation_type == "domain_violation"

    def test_impossible_monetary_range_is_quarantined(self) -> None:
        batch = _valid_batch(5)
        batch.loc[batch.index[0], "X12"] = 1e12
        report = validate_input_contract(batch, "strict")
        assert report.n_quarantined_rows == 1
        assert report.row_level_violations[0].violation_type == "range_violation"

    def test_clean_batch_has_no_violations(self) -> None:
        report = validate_input_contract(_valid_batch(10), "strict")
        assert report.n_quarantined_rows == 0
        assert report.n_valid_rows == 10

    def test_audit_mode_never_quarantines(self) -> None:
        batch = _valid_batch(5)
        batch.loc[batch.index[0], "X6"] = 15
        report = validate_input_contract(batch, "audit")
        assert report.quarantined_ids == [batch.loc[batch.index[0], "ID"]]
        assert report.n_valid_rows == 4  # profiled, not scored operationally


class TestCleanRowsAndQuarantine:
    def test_clean_rows_removes_only_quarantined_ids(self) -> None:
        batch = _valid_batch(5)
        batch.loc[batch.index[0], "X6"] = 15
        report = validate_input_contract(batch, "strict")
        cleaned = clean_rows(batch, report)
        assert len(cleaned) == 4
        assert report.quarantined_ids[0] not in cleaned["ID"].to_numpy()

    def test_clean_rows_is_noop_without_violations(self) -> None:
        batch = _valid_batch(5)
        report = validate_input_contract(batch, "strict")
        cleaned = clean_rows(batch, report)
        assert len(cleaned) == len(batch)

    def test_write_quarantine_creates_local_file_only(self, tmp_path: Path) -> None:
        batch = _valid_batch(5)
        batch.loc[batch.index[0], "X6"] = 15
        report = validate_input_contract(batch, "strict")
        path = write_quarantine(batch, report, repo_root=tmp_path)
        assert path is not None
        assert path.is_file()
        assert "quarantine_reasons" in pd.read_csv(path).columns

    def test_write_quarantine_returns_none_when_nothing_quarantined(self, tmp_path: Path) -> None:
        report = validate_input_contract(_valid_batch(5), "strict")
        assert write_quarantine(_valid_batch(5), report, repo_root=tmp_path) is None


class TestImpactProfile:
    def test_impact_profile_counts_by_violation_type(self) -> None:
        batch = _valid_batch(5)
        batch.loc[batch.index[0], "X6"] = 15
        batch.loc[batch.index[1], "X7"] = 20
        report = validate_input_contract(batch, "audit")
        assert report.impact_profile.get("domain_violation") == 2
