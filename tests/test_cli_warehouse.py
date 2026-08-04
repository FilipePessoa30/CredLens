"""CLI smoke tests for `credlens warehouse {prepare,build,test,status,query,
docs}` (Phase 5 section 13). Real dbt builds against real smoke-scale
generated data - no mocking, matching this test suite's existing
convention for the synthetic-generation CLI."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.cli import main
from credlens.generation.config import load_generation_config
from credlens.generation.orchestrator import generate_scenario
from credlens.warehouse.build import _rmtree_with_retry, build_dir_for

# Fase 11B - see tests/test_warehouse_build.py's own comment: this file
# was never marked slow, causing the dedicated CI job's slow-test step
# to exit 5 ("no tests collected").
pytestmark = pytest.mark.slow

_SEED = 615_302
_BUILD_ID = "BUILD_pytest_cli_warehouse"


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
def a_built_warehouse(a_real_run: str) -> Iterator[str]:
    exit_code = main(
        ["warehouse", "build", "--run-id", a_real_run, "--build-id", _BUILD_ID, "--force"]
    )
    assert exit_code == 0
    yield _BUILD_ID
    build_dir = build_dir_for(_BUILD_ID)
    if build_dir.exists():
        try:
            _rmtree_with_retry(build_dir)
        except PermissionError:
            shutil.rmtree(build_dir, ignore_errors=True)


class TestPrepare:
    def test_prepare_by_run_id_succeeds(
        self, a_real_run: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["warehouse", "prepare", "--run-id", a_real_run])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Result: OK" in captured.out

    def test_prepare_json_output(self, a_real_run: str, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["warehouse", "prepare", "--run-id", a_real_run, "--json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload[0]["run_id"] == a_real_run

    def test_prepare_unknown_run_id_fails_cleanly(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["warehouse", "prepare", "--run-id", "RUN_does_not_exist_0000"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Error:" in captured.out

    def test_run_id_and_suite_id_are_mutually_exclusive(self) -> None:
        with pytest.raises(SystemExit):
            main(
                [
                    "warehouse",
                    "prepare",
                    "--run-id",
                    "RUN_x",
                    "--suite-id",
                    "SUITE_y",
                ]
            )

    def test_neither_run_id_nor_suite_id_fails_cleanly(self) -> None:
        with pytest.raises(SystemExit):
            main(["warehouse", "prepare"])


class TestBuild:
    def test_build_succeeds(
        self, a_built_warehouse: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        captured = capsys.readouterr()  # drain the fixture's own build output
        exit_code = main(["warehouse", "status", "--build-id", a_built_warehouse])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "final_status:           success" in captured.out

    def test_build_existing_destination_without_force_fails_cleanly(
        self, a_real_run: str, a_built_warehouse: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            ["warehouse", "build", "--run-id", a_real_run, "--build-id", a_built_warehouse]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Error:" in captured.out
        assert "already exists" in captured.out

    def test_build_invalid_run_id_fails_cleanly(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(
            ["warehouse", "build", "--run-id", "RUN_does_not_exist_0000", "--build-id", "BUILD_x"]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Error:" in captured.out

    def test_build_json_output(
        self, a_real_run: str, a_built_warehouse: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            [
                "warehouse",
                "build",
                "--run-id",
                a_real_run,
                "--build-id",
                a_built_warehouse,
                "--force",
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["build_id"] == a_built_warehouse
        assert payload["final_status"] == "success"


class TestStatusQueryTestDocs:
    def test_status_json(self, a_built_warehouse: str, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["warehouse", "status", "--build-id", a_built_warehouse, "--json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["build_id"] == a_built_warehouse
        assert payload["analytical_fingerprint"]

    def test_status_unknown_build_id_fails_cleanly(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["warehouse", "status", "--build-id", "BUILD_does_not_exist"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Error:" in captured.out

    def test_query_named_demo_query(
        self, a_built_warehouse: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            ["warehouse", "query", "--build-id", a_built_warehouse, "--name", "portfolio_monthly"]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "row(s)." in captured.out

    def test_query_unknown_name_fails_cleanly(
        self, a_built_warehouse: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            ["warehouse", "query", "--build-id", a_built_warehouse, "--name", "not_a_query"]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Error:" in captured.out

    def test_query_unknown_build_id_fails_cleanly(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(
            [
                "warehouse",
                "query",
                "--build-id",
                "BUILD_does_not_exist",
                "--name",
                "portfolio_monthly",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Error:" in captured.out

    def test_query_json_output(
        self, a_built_warehouse: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            [
                "warehouse",
                "query",
                "--build-id",
                a_built_warehouse,
                "--name",
                "portfolio_monthly",
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert isinstance(payload, list)

    def test_test_command_reruns_tests(
        self, a_built_warehouse: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["warehouse", "test", "--build-id", a_built_warehouse])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "failed:  0" in captured.out

    def test_test_command_unknown_build_id_fails_cleanly(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["warehouse", "test", "--build-id", "BUILD_does_not_exist"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Error:" in captured.out

    def test_test_command_json_output(
        self, a_built_warehouse: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["warehouse", "test", "--build-id", a_built_warehouse, "--json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["success"] is True

    def test_docs_command_generates_site(
        self, a_built_warehouse: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["warehouse", "docs", "--build-id", a_built_warehouse])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "dbt docs generated:" in captured.out

    def test_docs_command_unknown_build_id_fails_cleanly(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["warehouse", "docs", "--build-id", "BUILD_does_not_exist"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Error:" in captured.out

    def test_reconcile_command_all_checks_pass(
        self, a_built_warehouse: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["warehouse", "reconcile", "--build-id", a_built_warehouse])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Result: OK (8 check(s))" in captured.out
        assert "approval_rate" in captured.out
        assert "MISMATCH" not in captured.out

    def test_reconcile_json_output(
        self, a_built_warehouse: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["warehouse", "reconcile", "--build-id", a_built_warehouse, "--json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert len(payload) == 8
        assert all(check["passed"] for check in payload)

    def test_reconcile_unknown_build_id_fails_cleanly(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["warehouse", "reconcile", "--build-id", "BUILD_does_not_exist"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Error:" in captured.out


class TestDispatchFallback:
    def test_no_subcommand_prints_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["warehouse"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "usage: credlens warehouse" in captured.out
