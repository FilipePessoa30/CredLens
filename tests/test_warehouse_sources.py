"""Tests for credlens.warehouse.sources.resolve_sources: the warehouse must
never load an unvalidated, incomplete, quarantined, or unsupported-version
run, and selection must always be explicit (Phase 5 section 5)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.generation.config import load_generation_config
from credlens.generation.orchestrator import generate_scenario
from credlens.generation.quarantine import run_incident
from credlens.generation.suite import generate_suite
from credlens.warehouse.sources import SourceSelectionError, _load_one_run, resolve_sources

_SEED = 734_501
_SUITE_SEED = 734_502
_QUARANTINE_BASE = Path("data/quarantine")


@pytest.fixture(scope="module")
def a_real_run() -> Iterator[str]:
    outcome = generate_scenario(scenario="baseline", scale_name="smoke", seed=_SEED, force=True)
    yield outcome.generation_run_id
    config = load_generation_config()
    for base in (config.output.operational_dir, config.output.truth_dir):
        path = Path(base) / outcome.generation_run_id
        if path.exists():
            shutil.rmtree(path)


@pytest.fixture(scope="module")
def a_real_suite() -> Iterator[str]:
    outcome = generate_suite(scale_name="smoke", seed=_SUITE_SEED, force=True)
    yield outcome.suite_id
    config = load_generation_config()
    for base in (config.output.operational_dir, config.output.truth_dir):
        base_path = Path(base)
        if not base_path.is_dir():
            continue
        for run_dir in base_path.iterdir():
            if str(_SUITE_SEED) in run_dir.name:
                shutil.rmtree(run_dir)
    manifest_path = Path("reports/synthetic_validation/suites") / f"SUITE_smoke_{_SUITE_SEED}.json"
    if manifest_path.is_file():
        manifest_path.unlink()


class TestResolveByRunId:
    def test_returns_one_source_record(self, a_real_run: str) -> None:
        sources = resolve_sources(run_id=a_real_run)
        assert len(sources) == 1
        record = sources[0]
        assert record.run_id == a_real_run
        assert record.suite_id is None
        assert record.scenario == "baseline"
        assert record.generator_version
        assert record.global_content_hash
        assert record.row_counts["customers"] > 0

    def test_unknown_run_id_raises(self) -> None:
        with pytest.raises(SourceSelectionError, match="No run found"):
            resolve_sources(run_id="RUN_does_not_exist_0000000000")


class TestResolveBySuiteId:
    def test_returns_baseline_and_every_scenario(self, a_real_suite: str) -> None:
        sources = resolve_sources(suite_id=a_real_suite)
        assert len(sources) == 5
        scenarios = {s.scenario for s in sources}
        assert scenarios == {
            "baseline",
            "policy_expansion",
            "policy_tightening",
            "macroeconomic_stress",
            "collections_change",
        }
        assert all(s.suite_id == a_real_suite for s in sources)

    def test_unknown_suite_id_raises(self) -> None:
        with pytest.raises(SourceSelectionError):
            resolve_sources(suite_id="SUITE_does_not_exist_0000000000")


class TestSelectionMustBeExplicit:
    def test_neither_run_id_nor_suite_id_raises(self) -> None:
        with pytest.raises(SourceSelectionError, match="Exactly one"):
            resolve_sources()

    def test_both_run_id_and_suite_id_raises(self, a_real_run: str, a_real_suite: str) -> None:
        with pytest.raises(SourceSelectionError, match="Exactly one"):
            resolve_sources(run_id=a_real_run, suite_id=a_real_suite)


class TestQuarantineNeverLoaded:
    def test_quarantined_run_not_reachable_via_synthetic_root(self) -> None:
        outcome = generate_scenario(
            scenario="contract_coverage", scale_name="smoke", seed=909_909, force=True
        )
        try:
            operational_dir = outcome.operational_dir / "operational"
            incident_result = run_incident(
                operational_dir,
                "duplicate_primary_key",
                _QUARANTINE_BASE,
                outcome.generation_run_id,
            )
            # A quarantined run's id was never promoted under data/synthetic/
            # (only under data/quarantine/) - resolve_sources must never find
            # it there, exactly like any other nonexistent run id.
            with pytest.raises(SourceSelectionError, match="No run found"):
                resolve_sources(run_id=incident_result.quarantine_run_id)
        finally:
            config = load_generation_config()
            for base in (config.output.operational_dir, config.output.truth_dir):
                path = Path(base) / outcome.generation_run_id
                if path.exists():
                    shutil.rmtree(path)
            if _QUARANTINE_BASE.exists():
                shutil.rmtree(_QUARANTINE_BASE)

    def test_load_one_run_rejects_a_quarantine_path_segment(self, tmp_path: Path) -> None:
        # Defense-in-depth unit test: even if a caller ever passed an
        # operational_root that itself resolves under a "quarantine"
        # segment, _load_one_run must refuse it outright - this can never
        # happen through the real config (config.output.operational_dir is
        # always data/synthetic/), so it is exercised directly here.
        quarantine_root = tmp_path / "data" / "quarantine"
        run_dir = quarantine_root / "RUN_fake_0000"
        (run_dir / "operational").mkdir(parents=True)
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
        with pytest.raises(SourceSelectionError, match="quarantine"):
            _load_one_run("RUN_fake_0000", quarantine_root, suite_id=None)


class TestManifestValidation:
    def test_incomplete_status_rejected(self, tmp_path: Path) -> None:
        import json

        run_dir = tmp_path / "RUN_incomplete_0000"
        (run_dir / "operational").mkdir(parents=True)
        (run_dir / "manifest.json").write_text(
            json.dumps({"status": "failed", "validation_passed": False}), encoding="utf-8"
        )
        with pytest.raises(SourceSelectionError, match="status"):
            _load_one_run("RUN_incomplete_0000", tmp_path, suite_id=None)

    def test_unsupported_contract_version_set_rejected(self, tmp_path: Path) -> None:
        import json

        run_dir = tmp_path / "RUN_old_contract_0000"
        (run_dir / "operational").mkdir(parents=True)
        (run_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "validation_passed": True,
                    "global_content_hash": "deadbeef",
                    "contract_version_set": "phase4a-v1",
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(SourceSelectionError, match="contract_version_set"):
            _load_one_run("RUN_old_contract_0000", tmp_path, suite_id=None)
