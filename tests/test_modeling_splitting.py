"""Tests for credlens.modeling.splitting (Phase 8 section 10): stratified
60/20/20, no out-of-time invention, seed-reproducible, the test partition
is locked by an ID-keyed table rather than re-derivation alone."""

from __future__ import annotations

from dataclasses import replace as dc_replace
from pathlib import Path

import pandas as pd
import pytest

from credlens.modeling.contracts import EvaluationConfig, load_evaluation_config
from credlens.modeling.splitting import (
    SplitAssignment,
    SplitError,
    apply_split_assignment_table,
    create_split,
    load_split_assignment_table,
    write_split_assignment_table,
)


@pytest.fixture
def config() -> EvaluationConfig:
    return load_evaluation_config()


def _split(df: pd.DataFrame, config: EvaluationConfig, seed: int = 42) -> SplitAssignment:
    return create_split(df, id_column="ID", target_column="Y", config=config, seed=seed)


class TestCreateSplit:
    def test_sizes_match_configured_fractions(
        self, tiny_uci_frame: pd.DataFrame, config: EvaluationConfig
    ) -> None:
        assignment = _split(tiny_uci_frame, config)
        n = len(tiny_uci_frame)
        m = assignment.manifest
        assert m.n_train == round(n * 0.6)
        assert m.n_validation + m.n_test == n - m.n_train

    def test_partitions_do_not_overlap(
        self, tiny_uci_frame: pd.DataFrame, config: EvaluationConfig
    ) -> None:
        assignment = _split(tiny_uci_frame, config)
        train = set(assignment.train_index)
        val = set(assignment.validation_index)
        test = set(assignment.test_index)
        assert not (train & val)
        assert not (train & test)
        assert not (val & test)
        assert len(train | val | test) == len(tiny_uci_frame)

    def test_stratification_keeps_prevalence_close_across_partitions(
        self, tiny_uci_frame: pd.DataFrame, config: EvaluationConfig
    ) -> None:
        m = _split(tiny_uci_frame, config).manifest
        assert abs(m.train_prevalence - m.test_prevalence) < 0.1
        assert abs(m.train_prevalence - m.validation_prevalence) < 0.1

    def test_same_seed_is_fully_reproducible(
        self, tiny_uci_frame: pd.DataFrame, config: EvaluationConfig
    ) -> None:
        first = _split(tiny_uci_frame, config, seed=42)
        second = _split(tiny_uci_frame, config, seed=42)
        assert first.manifest.train_id_hash == second.manifest.train_id_hash
        assert first.manifest.validation_id_hash == second.manifest.validation_id_hash
        assert first.manifest.test_id_hash == second.manifest.test_id_hash

    def test_different_seed_produces_a_different_split(
        self, tiny_uci_frame: pd.DataFrame, config: EvaluationConfig
    ) -> None:
        first = _split(tiny_uci_frame, config, seed=42)
        second = _split(tiny_uci_frame, config, seed=43)
        assert first.manifest.test_id_hash != second.manifest.test_id_hash

    def test_manifest_to_dict_round_trips(
        self, tiny_uci_frame: pd.DataFrame, config: EvaluationConfig
    ) -> None:
        d = _split(tiny_uci_frame, config).manifest.to_dict()
        assert d["seed"] == 42
        assert d["n_total"] == len(tiny_uci_frame)

    def test_fractions_must_sum_to_one(
        self, tiny_uci_frame: pd.DataFrame, config: EvaluationConfig
    ) -> None:
        broken_split = dict(config.raw["split"])
        broken_split["test_fraction"] = 0.5
        broken_config = dc_replace(config, raw={**config.raw, "split": broken_split})
        with pytest.raises(SplitError, match="must sum to 1"):
            _split(tiny_uci_frame, broken_config)


class TestSplitAssignmentTable:
    def test_write_and_reload_round_trips(
        self, tiny_uci_frame: pd.DataFrame, config: EvaluationConfig, tmp_path: Path
    ) -> None:
        assignment = _split(tiny_uci_frame, config)
        path = tmp_path / "split_assignment.csv"
        write_split_assignment_table(tiny_uci_frame, assignment, id_column="ID", path=path)
        table = load_split_assignment_table(path)
        assert set(table["split"]) == {"train", "validation", "test"}
        assert len(table) == len(tiny_uci_frame)

        reloaded = apply_split_assignment_table(tiny_uci_frame, table, id_column="ID")
        assert reloaded.manifest.train_id_hash == assignment.manifest.train_id_hash
        assert reloaded.manifest.validation_id_hash == assignment.manifest.validation_id_hash
        assert reloaded.manifest.test_id_hash == assignment.manifest.test_id_hash

    def test_load_missing_table_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SplitError, match="not found"):
            load_split_assignment_table(tmp_path / "nope.csv")

    def test_apply_with_missing_rows_raises(self, tiny_uci_frame: pd.DataFrame) -> None:
        table = pd.DataFrame({"id": [tiny_uci_frame["ID"].iloc[0]], "split": ["train"]})
        with pytest.raises(SplitError, match="no split assignment"):
            apply_split_assignment_table(tiny_uci_frame, table, id_column="ID")
