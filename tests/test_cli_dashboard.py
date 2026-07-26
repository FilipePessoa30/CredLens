"""CLI smoke tests for `credlens dashboard {validate,export-demo,status}`
(Phase 7 section 19). `run` is not invoked here (it launches a blocking
Streamlit subprocess) - its --build-id/--demo mutual exclusivity is
proven directly via argparse instead."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.analysis.runner import run_analysis
from credlens.cli import main
from credlens.generation.suite import generate_suite
from credlens.generation.testing_support import (
    isolated_manifest_dir,
    isolated_output_dirs,
    safe_rmtree,
)
from credlens.warehouse.build import _rmtree_with_retry, build_dir_for, run_build

_SEED = 703_513
_BUILD_ID = "BUILD_pytest_cli_dashboard"


@pytest.fixture(scope="module")
def isolated_suite(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path, Path]]:
    tmp_path = tmp_path_factory.mktemp("cli_dashboard")
    operational_dir, truth_dir = isolated_output_dirs(tmp_path)
    manifest_dir = isolated_manifest_dir(tmp_path)
    outcome = generate_suite(
        scale_name="smoke",
        seed=_SEED,
        force=True,
        output_dirs=(operational_dir, truth_dir),
        manifest_dir=manifest_dir,
    )
    yield outcome.suite_id, operational_dir, manifest_dir
    safe_rmtree(tmp_path, allowed_root=tmp_path)


@pytest.fixture(scope="module")
def a_built_suite(isolated_suite: tuple[str, Path, Path]) -> Iterator[str]:
    suite_id, operational_dir, manifest_dir = isolated_suite
    manifest = run_build(
        suite_id=suite_id,
        build_id=_BUILD_ID,
        force=True,
        operational_root=operational_dir,
        manifest_dir=manifest_dir,
    )
    assert manifest.final_status == "success"
    yield manifest.build_id
    build_dir = build_dir_for(_BUILD_ID)
    if build_dir.exists():
        try:
            _rmtree_with_retry(build_dir)
        except PermissionError:
            shutil.rmtree(build_dir, ignore_errors=True)


class TestDashboardValidate:
    def test_validate_a_real_build(
        self, a_built_suite: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["dashboard", "validate", "--build-id", a_built_suite])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Result: OK" in captured.out

    def test_validate_json_output(
        self, a_built_suite: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["dashboard", "validate", "--build-id", a_built_suite, "--json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["ok"] is True
        assert payload["mode"] == "warehouse"

    def test_validate_unknown_build_fails_cleanly(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["dashboard", "validate", "--build-id", "BUILD_does_not_exist_anywhere"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Error" in captured.out

    def test_build_id_and_demo_are_mutually_exclusive(self) -> None:
        with pytest.raises(SystemExit):
            main(["dashboard", "validate", "--build-id", "X", "--demo"])

    def test_neither_build_id_nor_demo_fails_cleanly(self) -> None:
        with pytest.raises(SystemExit):
            main(["dashboard", "validate"])


class TestDashboardExportDemo:
    def test_export_demo_builds_a_package(
        self, a_built_suite: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report_dir = tmp_path / "report"
        run_analysis(build_id=a_built_suite, output_dir=report_dir, include_benchmark=False)
        out_dir = tmp_path / "demo"

        exit_code = main(
            [
                "dashboard",
                "export-demo",
                "--build-id",
                a_built_suite,
                "--analysis-output-dir",
                str(report_dir),
                "--output-dir",
                str(out_dir),
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        assert (out_dir / "manifest.json").is_file()
        assert "tables:" in captured.out

    def test_export_demo_refuses_overwrite_without_force(
        self, a_built_suite: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report_dir = tmp_path / "report2"
        run_analysis(build_id=a_built_suite, output_dir=report_dir, include_benchmark=False)
        out_dir = tmp_path / "demo2"
        main(
            [
                "dashboard",
                "export-demo",
                "--build-id",
                a_built_suite,
                "--analysis-output-dir",
                str(report_dir),
                "--output-dir",
                str(out_dir),
            ]
        )
        exit_code = main(
            [
                "dashboard",
                "export-demo",
                "--build-id",
                a_built_suite,
                "--analysis-output-dir",
                str(report_dir),
                "--output-dir",
                str(out_dir),
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "already exists" in captured.out


class TestDashboardStatus:
    def test_status_reports_available_builds(
        self, a_built_suite: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["dashboard", "status", "--json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert "available_builds" in payload
        assert "demo_package" in payload


class TestDashboardRunArgumentValidation:
    def test_run_requires_build_id_or_demo(self) -> None:
        with pytest.raises(SystemExit):
            main(["dashboard", "run"])

    def test_run_rejects_both_build_id_and_demo(self) -> None:
        with pytest.raises(SystemExit):
            main(["dashboard", "run", "--build-id", "X", "--demo"])
