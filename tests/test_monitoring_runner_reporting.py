"""Tests for credlens.monitoring.runner/reporting - the full Phase 9
monitoring-simulation pipeline (reference -> batches -> run -> alerts ->
bilingual report), on the real, isolated, full 30,000-row pipeline.

Marked `slow`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from credlens.monitoring import reporting
from credlens.monitoring.runner import MonitoringRunError, load_run

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def reference_id(phase9_isolated_repo_root: Path, phase9_model_id: str) -> str:
    return reporting.create_reference(phase9_model_id, repo_root=phase9_isolated_repo_root)


@pytest.fixture(scope="module")
def batch_set_id(phase9_isolated_repo_root: Path, reference_id: str) -> str:
    return reporting.simulate_batches(reference_id, repo_root=phase9_isolated_repo_root)


@pytest.fixture(scope="module")
def run_id(phase9_isolated_repo_root: Path, reference_id: str, batch_set_id: str) -> str:
    return reporting.run(reference_id, batch_set_id, repo_root=phase9_isolated_repo_root)


class TestCreateReferenceAndBatches:
    def test_reference_id_is_deterministic(self, phase9_model_id: str, reference_id: str) -> None:
        assert reference_id == f"REF_{phase9_model_id}"

    def test_batch_set_id_is_deterministic(self, reference_id: str, batch_set_id: str) -> None:
        assert batch_set_id == f"BATCHSET_{reference_id}"


class TestRun:
    def test_run_produces_12_batches_with_one_blocked(
        self, phase9_isolated_repo_root: Path, run_id: str
    ) -> None:
        record = load_run(run_id, repo_root=phase9_isolated_repo_root)
        assert record["n_batches"] == 12
        blocked = [b for b in record["batches"] if b["blocked"]]
        assert len(blocked) == 1
        assert blocked[0]["simulation_scenario"] == "corrupted_schema"

    def test_label_delay_batch_marks_labels_pending(
        self, phase9_isolated_repo_root: Path, run_id: str
    ) -> None:
        record = load_run(run_id, repo_root=phase9_isolated_repo_root)
        label_delay_batch = next(
            b for b in record["batches"] if b["simulation_scenario"] == "label_delay"
        )
        assert label_delay_batch["performance_drift"] == "labels_pending"

    def test_baseline_batch_has_few_alerts(
        self, phase9_isolated_repo_root: Path, run_id: str
    ) -> None:
        rate = reporting.false_alert_rate(run_id, repo_root=phase9_isolated_repo_root)
        assert 0.0 <= rate <= 0.5

    def test_missing_reference_raises(self, phase9_isolated_repo_root: Path) -> None:
        with pytest.raises(MonitoringRunError):
            load_run("RUN_never_existed", repo_root=phase9_isolated_repo_root)


class TestReportAndValidate:
    def test_writes_bilingual_reports_with_mandatory_labels(
        self, phase9_isolated_repo_root: Path, run_id: str
    ) -> None:
        written = reporting.write_monitoring_reports(run_id, repo_root=phase9_isolated_repo_root)
        en_text = written["monitoring_report.md"].read_text(encoding="utf-8")
        pt_text = written["monitoring_report.pt-BR.md"].read_text(encoding="utf-8")
        assert "Monitoring simulation on a historical public benchmark" in en_text
        assert "Simulação de monitoramento" in pt_text
        manifest_path = written["manifest.json"]
        assert manifest_path.is_file()

    def test_validate_run_passes_structural_check(
        self, phase9_isolated_repo_root: Path, run_id: str
    ) -> None:
        assert reporting.validate_run(run_id, repo_root=phase9_isolated_repo_root) is True
