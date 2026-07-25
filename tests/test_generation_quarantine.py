"""Tests for credlens.generation.quarantine: every controlled defect must
actually fail strict contract validation with its documented error code,
and the broken copy must land under data/quarantine/, never
data/synthetic/ (Phase 4B section 10)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.generation.config import load_generation_config
from credlens.generation.orchestrator import generate_scenario
from credlens.generation.quarantine import INCIDENTS, IncidentError, run_incident

_SEED = 424_242
_QUARANTINE_BASE = Path("data/quarantine")


@pytest.fixture(scope="module")
def source_run() -> Iterator[Path]:
    # contract_coverage guarantees a terminal-status snapshot exists,
    # needed by the incoherent_snapshot incident.
    outcome = generate_scenario(
        scenario="contract_coverage", scale_name="smoke", seed=_SEED, force=True
    )
    operational_dir = outcome.operational_dir / "operational"
    yield operational_dir, outcome.generation_run_id  # type: ignore[misc]
    config = load_generation_config()
    for base in (config.output.operational_dir, config.output.truth_dir):
        path = Path(base) / outcome.generation_run_id
        if path.exists():
            shutil.rmtree(path)


@pytest.fixture(autouse=True)
def cleanup_quarantine() -> Iterator[None]:
    yield
    if _QUARANTINE_BASE.exists():
        shutil.rmtree(_QUARANTINE_BASE)


class TestEveryIncident:
    @pytest.mark.parametrize("incident_id", sorted(INCIDENTS))
    def test_incident_fails_strict_validation_as_expected(
        self, incident_id: str, source_run: tuple[Path, str]
    ) -> None:
        operational_dir, run_id = source_run
        outcome = run_incident(operational_dir, incident_id, _QUARANTINE_BASE, run_id)

        assert outcome.found_expected_error is True
        assert outcome.expected_error_code in str(outcome.error_codes_found)
        assert outcome.quarantine_dir.is_dir()
        assert not str(outcome.quarantine_dir).startswith("data\\synthetic\\")
        assert not str(outcome.quarantine_dir).startswith("data/synthetic/")

        manifest_path = outcome.quarantine_dir / "quarantine_manifest.json"
        assert manifest_path.is_file()
        import json

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "quarantined_expected_failure"
        assert manifest["found_expected_error"] is True

        generation_runs_path = outcome.quarantine_dir / "operational" / "generation_runs.parquet"
        if generation_runs_path.is_file():
            import pandas as pd

            gr = pd.read_parquet(generation_runs_path)
            assert (gr["status"] == "quarantined_expected_failure").all()
            assert "completed" not in gr["status"].to_numpy()

    def test_unknown_incident_is_rejected(self, source_run: tuple[Path, str]) -> None:
        operational_dir, run_id = source_run
        with pytest.raises(IncidentError, match="Unknown incident"):
            run_incident(operational_dir, "not_a_real_incident", _QUARANTINE_BASE, run_id)


class TestIncidentSelfCheck:
    def test_incident_that_fails_to_produce_its_own_error_raises(
        self, source_run: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import credlens.generation.quarantine as quarantine_module

        operational_dir, run_id = source_run

        # An injector that changes nothing - the resulting tables are
        # still fully valid, so strict validation will NOT produce the
        # incident's declared expected_error_code, and run_incident must
        # refuse to quarantine it silently.
        noop_incident = quarantine_module.IncidentDefinition(
            incident_id="noop",
            description="Does nothing - used to test the self-check.",
            expected_error_code="PK_DUPLICATE",
            expected_contract="customers",
            inject=lambda tables: {name: df.copy() for name, df in tables.items()},
        )
        monkeypatch.setitem(quarantine_module.INCIDENTS, "noop", noop_incident)

        with pytest.raises(IncidentError, match="did not produce the failure"):
            run_incident(operational_dir, "noop", _QUARANTINE_BASE, run_id)
