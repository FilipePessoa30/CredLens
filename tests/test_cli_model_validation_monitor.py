"""CLI tests for the Phase 9 `credlens model {validate-independent,
audit-collinearity,audit-negative-controls,compare-candidates,register-
challenger}` and `credlens monitor {create-reference,simulate-batches,
run,status,alerts,report,validate}` subcommands.

Runs against the REAL repo (CLI commands default to `Path.cwd()`, same
as every other `credlens ...` subcommand), using a throwaway registered
model candidate (`TEST_cli9_model`, re-registered from the already-
trained/evaluated official `EXP_behavioral_default_v1` experiment) so
the monitoring artifacts this test produces never touch the official
`REF_MODEL_behavioral_default_v1` reference. Cleaned up in a module-
scoped fixture teardown. Marked `slow`.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.cli import main

pytestmark = pytest.mark.slow

_EXPERIMENT_ID = "EXP_behavioral_default_v1"  # already trained/evaluated/registered
_MODEL_ID = "TEST_cli9_model"
_CHALLENGER_MODEL_ID = "TEST_cli9_challenger"


def _cleanup() -> None:
    for path in (
        Path("reports/modeling/models") / f"{_MODEL_ID}.joblib",
        Path("reports/modeling/models") / f"{_MODEL_ID}.manifest.json",
        Path("reports/modeling/models") / f"{_CHALLENGER_MODEL_ID}.joblib",
        Path("reports/modeling/models") / f"{_CHALLENGER_MODEL_ID}.manifest.json",
        Path("reports/model_validation/lifecycle") / f"{_MODEL_ID}.json",
        Path("reports/model_validation/lifecycle") / f"{_CHALLENGER_MODEL_ID}.json",
    ):
        path.unlink(missing_ok=True)
    reference_id = f"REF_{_MODEL_ID}"
    for path in Path("reports/monitoring/reference").glob(f"{reference_id}*"):
        path.unlink(missing_ok=True)
    batch_set_dir = Path("reports/monitoring/runs") / f"BATCHSET_{reference_id}"
    if batch_set_dir.is_dir():
        shutil.rmtree(batch_set_dir, ignore_errors=True)
    for run_dir in Path("reports/monitoring/runs").glob(f"RUN_BATCHSET_{reference_id}_*"):
        shutil.rmtree(run_dir, ignore_errors=True)
    for path in Path("reports/monitoring/alerts").glob(f"RUN_BATCHSET_{reference_id}_*.json"):
        path.unlink(missing_ok=True)


@pytest.fixture(scope="module", autouse=True)
def clean_before_and_after() -> Iterator[None]:
    _cleanup()
    yield
    _cleanup()


@pytest.fixture(scope="module")
def registered_throwaway_model() -> str:
    """Registers the same official experiment under a throwaway model_id
    - the gates were already proven to pass, so this reuses that fact
    rather than re-tuning anything."""
    exit_code = main(
        ["model", "register", "--experiment-id", _EXPERIMENT_ID, "--model-id", _MODEL_ID]
    )
    assert exit_code == 0
    return _MODEL_ID


class TestModelValidationCommands:
    def test_validate_independent(
        self, registered_throwaway_model: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            ["model", "validate-independent", "--model-id", registered_throwaway_model, "--ci"]
        )
        captured = capsys.readouterr()
        assert "Decision:" in captured.out
        assert exit_code in (
            0,
            1,
        )  # --ci cannot reach the negative-controls alpha, decision may fail

    def test_audit_collinearity(
        self, registered_throwaway_model: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            ["model", "audit-collinearity", "--model-id", registered_throwaway_model, "--json"]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert "condition_number" in payload

    def test_audit_negative_controls_ci(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(
            [
                "model",
                "audit-negative-controls",
                "--experiment-id",
                _EXPERIMENT_ID,
                "--ci",
                "--json",
            ]
        )
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["n_permutations"] == 10
        assert exit_code in (0, 1)

    def test_register_challenger(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(
            [
                "model",
                "register-challenger",
                "--experiment-id",
                _EXPERIMENT_ID,
                "--model-id",
                _CHALLENGER_MODEL_ID,
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "challenger" in captured.out

    def test_compare_candidates(
        self, registered_throwaway_model: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(
            [
                "model",
                "register-challenger",
                "--experiment-id",
                _EXPERIMENT_ID,
                "--model-id",
                _CHALLENGER_MODEL_ID,
            ]
        )
        capsys.readouterr()
        exit_code = main(
            ["model", "compare-candidates", "--experiment-id", _EXPERIMENT_ID, "--json"]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert len(payload) == 2


class TestMonitorCommands:
    def test_create_reference(
        self, registered_throwaway_model: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            ["monitor", "create-reference", "--model-id", registered_throwaway_model, "--json"]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["reference_id"] == f"REF_{registered_throwaway_model}"

    def test_simulate_batches(self, capsys: pytest.CaptureFixture[str]) -> None:
        reference_id = f"REF_{_MODEL_ID}"
        exit_code = main(["monitor", "simulate-batches", "--reference-id", reference_id, "--json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["batch_set_id"] == f"BATCHSET_{reference_id}"

    def test_run_status_alerts_report_validate(self, capsys: pytest.CaptureFixture[str]) -> None:
        reference_id = f"REF_{_MODEL_ID}"
        batch_set_id = f"BATCHSET_{reference_id}"
        exit_code = main(
            [
                "monitor",
                "run",
                "--reference-id",
                reference_id,
                "--batch-set",
                batch_set_id,
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        run_id = json.loads(captured.out)["run_id"]

        exit_code = main(["monitor", "status", "--run-id", run_id, "--json"])
        assert exit_code == 0
        capsys.readouterr()

        exit_code = main(["monitor", "alerts", "--run-id", run_id, "--json"])
        assert exit_code == 0
        capsys.readouterr()

        exit_code = main(["monitor", "report", "--run-id", run_id])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "monitoring_report" in captured.out

        exit_code = main(["monitor", "validate", "--run-id", run_id])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "OK" in captured.out


class TestCliErrorHandling:
    def test_monitor_no_subcommand_prints_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["monitor"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "usage: credlens monitor" in captured.out

    def test_validate_independent_unknown_model_fails_cleanly(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["model", "validate-independent", "--model-id", "TEST_does_not_exist"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Error" in captured.out

    def test_monitor_run_missing_required_args_raises_system_exit(self) -> None:
        with pytest.raises(SystemExit):
            main(["monitor", "run"])
