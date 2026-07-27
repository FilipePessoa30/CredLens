"""CLI tests for `credlens model {data-audit,validate-features,create-
split,train,evaluate,compare,explain,audit-groups,stress-test,register,
validate,predict-batch,report}` (Phase 8 section 32).

Runs against the REAL repo (CLI commands default to `Path.cwd()`, same
as every other `credlens ...` subcommand) using throwaway experiment_id/
model_id values that never collide with the official
`EXP_behavioral_default_v1`/`MODEL_behavioral_default_v1`, cleaned up in
a module-scoped fixture teardown. Marked `slow` - trains/evaluates on the
real 30,000-row UCI benchmark.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

from credlens.cli import main

pytestmark = pytest.mark.slow

_EXPERIMENT_ID = "TEST_cli_pipeline"
_MODEL_ID = "TEST_cli_model"


def _cleanup() -> None:
    for path in (
        Path("reports/modeling/experiments") / f"{_EXPERIMENT_ID}.json",
        Path("reports/modeling/experiments") / _EXPERIMENT_ID,
        Path("reports/modeling/models") / f"{_MODEL_ID}.joblib",
        Path("reports/modeling/models") / f"{_MODEL_ID}.manifest.json",
    ):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file():
            path.unlink(missing_ok=True)
    for pattern in ("tables", "figures"):
        for path in Path(f"reports/modeling/{pattern}").glob(f"{_EXPERIMENT_ID}__*"):
            path.unlink(missing_ok=True)


@pytest.fixture(scope="module", autouse=True)
def clean_before_and_after() -> Iterator[None]:
    _cleanup()
    yield
    _cleanup()


class TestDataAuditAndValidateFeatures:
    def test_data_audit(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["model", "data-audit", "--json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["num_rows"] == 30000

    def test_validate_features(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["model", "validate-features"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "OK" in captured.out


class TestStagedPipeline:
    def test_create_split(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(
            ["model", "create-split", "--experiment-id", _EXPERIMENT_ID, "--seed", "42"]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "18000" in captured.out

    def test_train(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["model", "train", "--experiment-id", _EXPERIMENT_ID, "--seed", "42"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "status:   trained" in captured.out

    def test_evaluate(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["model", "evaluate", "--experiment-id", _EXPERIMENT_ID])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "test ROC-AUC" in captured.out

    def test_compare(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["model", "compare", "--experiment-id", _EXPERIMENT_ID])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "logistic_regression" in captured.out

    def test_explain(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["model", "explain", "--experiment-id", _EXPERIMENT_ID])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Wrote coefficients" in captured.out

    def test_audit_groups(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["model", "audit-groups", "--experiment-id", _EXPERIMENT_ID])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "not a compliance assessment" in captured.out

    def test_stress_test(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["model", "stress-test", "--experiment-id", _EXPERIMENT_ID])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "PR-AUC degradation" in captured.out

    def test_register(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(
            ["model", "register", "--experiment-id", _EXPERIMENT_ID, "--model-id", _MODEL_ID]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "All gates passed" in captured.out

    def test_validate(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["model", "validate", "--model-id", _MODEL_ID])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Result: OK" in captured.out

    def test_predict_batch(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        sample = pd.read_csv("data/raw/uci_default_credit/default_of_credit_card_clients.csv").head(
            5
        )
        input_path = tmp_path / "batch.csv"
        sample.to_csv(input_path, index=False)
        output_path = tmp_path / "scored.csv"
        exit_code = main(
            [
                "model",
                "predict-batch",
                "--model-id",
                _MODEL_ID,
                "--input",
                str(input_path),
                "--output",
                str(output_path),
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "rows scored: 5" in captured.out
        scored = pd.read_csv(output_path)
        assert set(scored.columns) == {
            "pseudonymous_record_id",
            "predicted_default_probability",
            "risk_band",
            "model_version",
            "scoring_timestamp",
            "input_schema_version",
        }

    def test_predict_batch_missing_id_column_fails_cleanly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        input_path = tmp_path / "bad.csv"
        pd.DataFrame({"X1": [1, 2]}).to_csv(input_path, index=False)
        exit_code = main(
            ["model", "predict-batch", "--model-id", _MODEL_ID, "--input", str(input_path)]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Error" in captured.out

    def test_report(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(
            ["model", "report", "--experiment-id", _EXPERIMENT_ID, "--model-id", _MODEL_ID]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "manifest.json" in captured.out


class TestCliErrorHandling:
    def test_unknown_experiment_fails_cleanly(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["model", "evaluate", "--experiment-id", "TEST_does_not_exist"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Error" in captured.out

    def test_no_subcommand_prints_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["model"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "usage: credlens model" in captured.out

    def test_missing_required_experiment_id_raises_system_exit(self) -> None:
        with pytest.raises(SystemExit):
            main(["model", "train"])
