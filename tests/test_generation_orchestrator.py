"""Tests for credlens.generation.orchestrator: scenario gating, run-id
determinism, --force semantics, and - the core reproducibility
requirement - that the same seed+config+scenario+scale produces an
identical global_content_hash, and a different seed produces a
different one. See docs/synthetic_generation_implementation.md
"Reproducibility".
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.generation.config import load_generation_config
from credlens.generation.orchestrator import (
    RunAlreadyExistsError,
    ScenarioNotCalibratedError,
    generate_baseline,
)

_SEED_A = 555_000_111
_SEED_B = 555_000_222


def _cleanup(run_id: str) -> None:
    config = load_generation_config()
    for base in (config.output.operational_dir, config.output.truth_dir):
        path = Path(base) / run_id
        if path.exists():
            shutil.rmtree(path)


@pytest.fixture
def cleanup_runs() -> Iterator[list[str]]:
    created: list[str] = []
    yield created
    for run_id in created:
        _cleanup(run_id)


class TestScenarioGating:
    def test_non_calibrated_scenario_is_rejected_before_any_generation(self) -> None:
        # data_quality_incident has no generation.yaml as of Phase 4B -
        # unlike policy_expansion/policy_tightening/macroeconomic_stress/
        # collections_change/contract_coverage, which all became
        # executable this phase (see EXECUTABLE_SCENARIOS).
        with pytest.raises(ScenarioNotCalibratedError, match="requires_calibration"):
            generate_baseline(scenario="data_quality_incident", scale_name="smoke", seed=1)

    def test_unknown_scenario_is_also_rejected(self) -> None:
        with pytest.raises(ScenarioNotCalibratedError):
            generate_baseline(scenario="not_a_real_scenario", scale_name="smoke", seed=1)


class TestRunIdDeterminism:
    def test_same_inputs_produce_the_same_run_id(self, cleanup_runs: list[str]) -> None:
        outcome1 = generate_baseline(
            scenario="baseline", scale_name="smoke", seed=_SEED_A, force=True
        )
        cleanup_runs.append(outcome1.generation_run_id)
        outcome2 = generate_baseline(
            scenario="baseline", scale_name="smoke", seed=_SEED_A, force=True
        )

        assert outcome1.generation_run_id == outcome2.generation_run_id

    def test_different_seed_produces_a_different_run_id(self, cleanup_runs: list[str]) -> None:
        outcome_a = generate_baseline(
            scenario="baseline", scale_name="smoke", seed=_SEED_A, force=True
        )
        cleanup_runs.append(outcome_a.generation_run_id)
        outcome_b = generate_baseline(
            scenario="baseline", scale_name="smoke", seed=_SEED_B, force=True
        )
        cleanup_runs.append(outcome_b.generation_run_id)

        assert outcome_a.generation_run_id != outcome_b.generation_run_id


class TestForceSemantics:
    def test_existing_run_without_force_raises(self, cleanup_runs: list[str]) -> None:
        outcome = generate_baseline(
            scenario="baseline", scale_name="smoke", seed=_SEED_A, force=True
        )
        cleanup_runs.append(outcome.generation_run_id)

        with pytest.raises(RunAlreadyExistsError, match="already exists"):
            generate_baseline(scenario="baseline", scale_name="smoke", seed=_SEED_A, force=False)

    def test_force_overwrites_an_existing_run(self, cleanup_runs: list[str]) -> None:
        first = generate_baseline(scenario="baseline", scale_name="smoke", seed=_SEED_A, force=True)
        cleanup_runs.append(first.generation_run_id)
        second = generate_baseline(
            scenario="baseline", scale_name="smoke", seed=_SEED_A, force=True
        )

        assert second.generation_run_id == first.generation_run_id
        assert second.status == "completed"


class TestDeterministicContentHash:
    """The core reproducibility proof this phase requires: same
    seed/config/scenario/scale -> identical canonical content, seed
    changed -> different content."""

    def test_same_seed_produces_identical_global_content_hash(
        self, cleanup_runs: list[str]
    ) -> None:
        outcome1 = generate_baseline(
            scenario="baseline", scale_name="smoke", seed=_SEED_A, force=True
        )
        cleanup_runs.append(outcome1.generation_run_id)
        hash1 = outcome1.manifest["global_content_hash"]

        outcome2 = generate_baseline(
            scenario="baseline", scale_name="smoke", seed=_SEED_A, force=True
        )
        hash2 = outcome2.manifest["global_content_hash"]

        assert hash1 == hash2
        assert isinstance(hash1, str) and len(hash1) == 64

    def test_same_seed_produces_identical_per_table_row_counts(
        self, cleanup_runs: list[str]
    ) -> None:
        outcome1 = generate_baseline(
            scenario="baseline", scale_name="smoke", seed=_SEED_A, force=True
        )
        cleanup_runs.append(outcome1.generation_run_id)
        outcome2 = generate_baseline(
            scenario="baseline", scale_name="smoke", seed=_SEED_A, force=True
        )

        tables1 = outcome1.manifest["tables"]
        tables2 = outcome2.manifest["tables"]
        assert tables1 == tables2  # identical row counts AND identical per-table hashes

    def test_different_seed_produces_a_different_global_content_hash(
        self, cleanup_runs: list[str]
    ) -> None:
        outcome_a = generate_baseline(
            scenario="baseline", scale_name="smoke", seed=_SEED_A, force=True
        )
        cleanup_runs.append(outcome_a.generation_run_id)
        outcome_b = generate_baseline(
            scenario="baseline", scale_name="smoke", seed=_SEED_B, force=True
        )
        cleanup_runs.append(outcome_b.generation_run_id)

        assert (
            outcome_a.manifest["global_content_hash"] != outcome_b.manifest["global_content_hash"]
        )

    def test_different_seed_still_produces_valid_contracts(self, cleanup_runs: list[str]) -> None:
        outcome_b = generate_baseline(
            scenario="baseline", scale_name="smoke", seed=_SEED_B, force=True
        )
        cleanup_runs.append(outcome_b.generation_run_id)

        assert outcome_b.validation.contracts_passed is True
        assert outcome_b.status == "completed"


class TestPromotionWritesExpectedFiles:
    def test_promoted_run_has_manifest_config_snapshot_and_summary(
        self, cleanup_runs: list[str]
    ) -> None:
        outcome = generate_baseline(
            scenario="baseline", scale_name="smoke", seed=_SEED_A, force=True
        )
        cleanup_runs.append(outcome.generation_run_id)

        assert (outcome.operational_dir / "manifest.json").is_file()
        assert (outcome.operational_dir / "config_snapshot.yaml").is_file()
        assert (outcome.operational_dir / "contract_validation.json").is_file()
        assert (outcome.operational_dir / "generation_summary.json").is_file()
        assert (outcome.truth_dir / "truth_manifest.json").is_file()
        assert (outcome.truth_dir / "latent_customer_truth.parquet").is_file()
        assert (outcome.truth_dir / "latent_contract_truth.parquet").is_file()

    def test_truth_dir_is_physically_separate_from_operational_dir(
        self, cleanup_runs: list[str]
    ) -> None:
        outcome = generate_baseline(
            scenario="baseline", scale_name="smoke", seed=_SEED_A, force=True
        )
        cleanup_runs.append(outcome.generation_run_id)

        assert outcome.truth_dir != outcome.operational_dir
        assert "synthetic_truth" in str(outcome.truth_dir)
        assert not (outcome.operational_dir / "latent_customer_truth.parquet").exists()
