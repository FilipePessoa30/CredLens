"""Tests for credlens.monitoring.contracts/reference/batches (Phase 9
sections 13, 14) - needs a real registered model, so uses the shared
`phase9_isolated_repo_root` fixture. Marked `slow`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from credlens.monitoring.batches import (
    BatchBuildError,
    build_batches,
    load_batch,
    load_batch_manifest,
    write_batches,
)
from credlens.monitoring.contracts import (
    load_reference_config,
    load_scenarios_config,
    load_thresholds_config,
)
from credlens.monitoring.reference import (
    MonitoringReference,
    ReferenceError,
    build_reference,
    load_reference,
    load_reference_population,
    write_reference,
)

pytestmark = pytest.mark.slow


class TestContracts:
    def test_loads_all_three_configs(self, phase9_isolated_repo_root: Path) -> None:
        ref_cfg = load_reference_config(phase9_isolated_repo_root)
        thr_cfg = load_thresholds_config(phase9_isolated_repo_root)
        sc_cfg = load_scenarios_config(phase9_isolated_repo_root)
        assert ref_cfg.reference_config_version == "1.0.0"
        assert len(thr_cfg.states) == 4
        assert len(sc_cfg.batches) == 12
        assert sc_cfg.batch_size == 500


@pytest.fixture(scope="module")
def built_reference(
    phase9_isolated_repo_root: Path, phase9_model_id: str
) -> tuple[MonitoringReference, pd.DataFrame]:
    reference, population = build_reference(phase9_model_id, repo_root=phase9_isolated_repo_root)
    write_reference(reference, population, repo_root=phase9_isolated_repo_root)
    return reference, population


class TestReference:
    def test_reference_only_uses_train_and_validation(
        self, built_reference: tuple[MonitoringReference, pd.DataFrame]
    ) -> None:
        reference, population = built_reference
        assert reference.n_reference_rows == len(population)
        assert reference.n_reference_rows == 24000  # 18000 train + 6000 validation

    def test_feature_stats_cover_all_18_features(
        self, built_reference: tuple[MonitoringReference, pd.DataFrame]
    ) -> None:
        reference, _ = built_reference
        assert len(reference.feature_stats) == 18

    def test_write_reference_refuses_silent_overwrite(
        self,
        phase9_isolated_repo_root: Path,
        phase9_model_id: str,
        built_reference: tuple[MonitoringReference, pd.DataFrame],
    ) -> None:
        reference, population = built_reference
        with pytest.raises(ReferenceError):
            write_reference(reference, population, repo_root=phase9_isolated_repo_root)

    def test_load_reference_roundtrip(
        self,
        phase9_isolated_repo_root: Path,
        built_reference: tuple[MonitoringReference, pd.DataFrame],
    ) -> None:
        reference, _ = built_reference
        loaded = load_reference(reference.reference_id, repo_root=phase9_isolated_repo_root)
        assert loaded.reference_id == reference.reference_id

    def test_load_reference_population_roundtrip(
        self,
        phase9_isolated_repo_root: Path,
        built_reference: tuple[MonitoringReference, pd.DataFrame],
    ) -> None:
        reference, _ = built_reference
        table = load_reference_population(
            reference.reference_id, repo_root=phase9_isolated_repo_root
        )
        assert "score" in table.columns
        assert "y_true" in table.columns

    def test_missing_reference_raises(self, phase9_isolated_repo_root: Path) -> None:
        with pytest.raises(ReferenceError):
            load_reference("REF_never_built", repo_root=phase9_isolated_repo_root)


class TestBatches:
    def test_builds_12_non_overlapping_batches(
        self,
        phase9_isolated_repo_root: Path,
        phase9_model_id: str,
        built_reference: tuple[MonitoringReference, pd.DataFrame],
    ) -> None:
        scenarios_config = load_scenarios_config(phase9_isolated_repo_root)
        batches = build_batches(
            phase9_model_id, scenarios_config, repo_root=phase9_isolated_repo_root
        )
        assert len(batches) == 12
        all_ids = []
        for spec, batch_df in batches:
            assert len(batch_df) <= scenarios_config.batch_size
            # subgroup_composition_shift deliberately oversamples WITH
            # replacement (duplicates within its own batch, by design);
            # every other scenario partitions distinct, non-overlapping
            # rows of the locked test set.
            if spec["simulation_scenario"] not in (
                "corrupted_schema",
                "subgroup_composition_shift",
            ):
                all_ids.extend(batch_df["ID"].tolist())
        assert len(all_ids) == len(set(all_ids))  # no row reused across these batches

    def test_corrupted_schema_batch_drops_a_column(
        self, phase9_isolated_repo_root: Path, phase9_model_id: str
    ) -> None:
        scenarios_config = load_scenarios_config(phase9_isolated_repo_root)
        batches = build_batches(
            phase9_model_id, scenarios_config, repo_root=phase9_isolated_repo_root
        )
        corrupted = next(
            df for spec, df in batches if spec["simulation_scenario"] == "corrupted_schema"
        )
        assert "X6" not in corrupted.columns

    def test_write_and_load_batch_manifest(
        self, phase9_isolated_repo_root: Path, phase9_model_id: str
    ) -> None:
        scenarios_config = load_scenarios_config(phase9_isolated_repo_root)
        batches = build_batches(
            phase9_model_id, scenarios_config, repo_root=phase9_isolated_repo_root
        )
        write_batches("TEST_batchset_1", batches, repo_root=phase9_isolated_repo_root)
        manifest = load_batch_manifest("TEST_batchset_1", repo_root=phase9_isolated_repo_root)
        assert len(manifest["batches"]) == 12
        loaded_batch = load_batch("TEST_batchset_1", 1, repo_root=phase9_isolated_repo_root)
        assert len(loaded_batch) == 500

    def test_writing_batches_twice_is_refused(
        self, phase9_isolated_repo_root: Path, phase9_model_id: str
    ) -> None:
        scenarios_config = load_scenarios_config(phase9_isolated_repo_root)
        batches = build_batches(
            phase9_model_id, scenarios_config, repo_root=phase9_isolated_repo_root
        )
        with pytest.raises(BatchBuildError):
            write_batches("TEST_batchset_1", batches, repo_root=phase9_isolated_repo_root)
