"""Tests for the `credlens analysis` CLI group (Phase 6 section 19):
validate/run/scenarios/benchmark/status/reproduce, exercised through
`credlens.cli.main()` exactly as a real invocation would. Builds one real
isolated-root suite warehouse per module and reuses it read-only."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.cli import main
from credlens.generation.suite import generate_suite
from credlens.generation.testing_support import (
    isolated_manifest_dir,
    isolated_output_dirs,
    safe_rmtree,
)
from credlens.warehouse.build import _rmtree_with_retry, build_dir_for, run_build

_SEED = 703_505
_BUILD_ID = "BUILD_pytest_cli_analysis"


@pytest.fixture(scope="module")
def isolated_suite(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path, Path]]:
    tmp_path = tmp_path_factory.mktemp("cli_analysis")
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


class TestAnalysisHelp:
    def test_top_level_help_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        # argparse's own `--help` handling calls parser.exit(0), which
        # raises SystemExit(0) directly rather than returning from main().
        with pytest.raises(SystemExit) as exc_info:
            main(["analysis", "--help"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "validate" in out
        assert "run" in out
        assert "reproduce" in out

    def test_no_subcommand_prints_usage_and_exits_nonzero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["analysis"])
        assert exit_code == 1
        assert "usage: credlens analysis" in capsys.readouterr().out


class TestAnalysisValidateCommand:
    def test_valid_build_exits_zero(
        self, a_built_suite: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["analysis", "validate", "--build-id", a_built_suite])
        assert exit_code == 0
        assert "Result: OK" in capsys.readouterr().out

    def test_valid_build_json_output_parses(
        self, a_built_suite: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["analysis", "validate", "--build-id", a_built_suite, "--json"])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["valid"] is True
        assert payload["build_id"] == a_built_suite

    def test_nonexistent_build_exits_nonzero(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["analysis", "validate", "--build-id", "BUILD_totally_fake_0000"])
        assert exit_code == 1
        assert "Error:" in capsys.readouterr().out


class TestAnalysisRunCommand:
    def test_writes_report_tree_and_exits_zero(
        self, a_built_suite: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output_dir = tmp_path / "cli_report"
        exit_code = main(
            [
                "analysis",
                "run",
                "--build-id",
                a_built_suite,
                "--output-dir",
                str(output_dir),
                "--no-benchmark",
            ]
        )
        assert exit_code == 0
        assert (output_dir / "manifest.json").is_file()
        assert (output_dir / "executive_summary.md").is_file()
        out = capsys.readouterr().out
        assert "analysis_id:" in out

    def test_json_output_parses(
        self, a_built_suite: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output_dir = tmp_path / "cli_report_json"
        exit_code = main(
            [
                "analysis",
                "run",
                "--build-id",
                a_built_suite,
                "--output-dir",
                str(output_dir),
                "--no-benchmark",
                "--json",
            ]
        )
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["build_id"] == a_built_suite
        assert payload["final_status"] == "success"

    def test_rerun_without_force_refuses_to_overwrite(
        self, a_built_suite: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output_dir = tmp_path / "cli_report_overwrite"
        first = main(
            [
                "analysis",
                "run",
                "--build-id",
                a_built_suite,
                "--output-dir",
                str(output_dir),
                "--no-benchmark",
            ]
        )
        assert first == 0
        capsys.readouterr()

        second = main(
            [
                "analysis",
                "run",
                "--build-id",
                a_built_suite,
                "--output-dir",
                str(output_dir),
                "--no-benchmark",
            ]
        )
        assert second == 1
        assert "--force" in capsys.readouterr().out

    def test_rerun_with_force_overwrites_successfully(
        self, a_built_suite: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output_dir = tmp_path / "cli_report_force"
        first = main(
            [
                "analysis",
                "run",
                "--build-id",
                a_built_suite,
                "--output-dir",
                str(output_dir),
                "--no-benchmark",
            ]
        )
        assert first == 0
        capsys.readouterr()

        second = main(
            [
                "analysis",
                "run",
                "--build-id",
                a_built_suite,
                "--output-dir",
                str(output_dir),
                "--no-benchmark",
                "--force",
            ]
        )
        assert second == 0


class TestAnalysisScenariosCommand:
    def test_exits_zero_and_prints_composition(
        self, a_built_suite: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["analysis", "scenarios", "--build-id", a_built_suite])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "policy_expansion" in out

    def test_json_output_parses(
        self, a_built_suite: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["analysis", "scenarios", "--build-id", a_built_suite, "--json"])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert "scenario_comparison" in payload
        assert "composition_vs_performance" in payload


class TestAnalysisBenchmarkCommand:
    def test_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["analysis", "benchmark"])
        assert exit_code == 0

    def test_json_output_is_a_list(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["analysis", "benchmark", "--json"])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload, list)


class TestAnalysisStatusCommand:
    def test_status_reads_back_a_prior_run(
        self, a_built_suite: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output_dir = tmp_path / "cli_report_status"
        main(
            [
                "analysis",
                "run",
                "--build-id",
                a_built_suite,
                "--output-dir",
                str(output_dir),
                "--no-benchmark",
            ]
        )
        capsys.readouterr()

        exit_code = main(["analysis", "status", "--output-dir", str(output_dir)])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert a_built_suite in out

    def test_status_with_wrong_analysis_id_fails(
        self, a_built_suite: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output_dir = tmp_path / "cli_report_status_wrong_id"
        main(
            [
                "analysis",
                "run",
                "--build-id",
                a_built_suite,
                "--output-dir",
                str(output_dir),
                "--no-benchmark",
            ]
        )
        capsys.readouterr()

        exit_code = main(
            ["analysis", "status", "--output-dir", str(output_dir), "--analysis-id", "WRONG_ID"]
        )
        assert exit_code == 1

    def test_status_missing_manifest_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["analysis", "status", "--output-dir", str(tmp_path / "does_not_exist")])
        assert exit_code == 1
        assert "Error:" in capsys.readouterr().out

    def test_status_json_output_parses(
        self, a_built_suite: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output_dir = tmp_path / "cli_report_status_json"
        main(
            [
                "analysis",
                "run",
                "--build-id",
                a_built_suite,
                "--output-dir",
                str(output_dir),
                "--no-benchmark",
            ]
        )
        capsys.readouterr()

        exit_code = main(["analysis", "status", "--output-dir", str(output_dir), "--json"])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["build_id"] == a_built_suite


class TestAnalysisReproduceCommand:
    def test_reproduce_missing_manifest_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            ["analysis", "reproduce", "--output-dir", str(tmp_path / "does_not_exist")]
        )
        assert exit_code == 1
        assert "Error:" in capsys.readouterr().out

    def test_reproduce_with_wrong_analysis_id_fails(
        self, a_built_suite: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output_dir = tmp_path / "cli_report_reproduce_wrong_id"
        main(
            [
                "analysis",
                "run",
                "--build-id",
                a_built_suite,
                "--output-dir",
                str(output_dir),
                "--no-benchmark",
            ]
        )
        capsys.readouterr()

        exit_code = main(
            [
                "analysis",
                "reproduce",
                "--output-dir",
                str(output_dir),
                "--analysis-id",
                "WRONG_ID",
            ]
        )
        assert exit_code == 1
        assert "Error:" in capsys.readouterr().out

    def test_reproduce_matches_the_original(
        self, a_built_suite: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output_dir = tmp_path / "cli_report_reproduce_src"
        main(
            [
                "analysis",
                "run",
                "--build-id",
                a_built_suite,
                "--output-dir",
                str(output_dir),
                "--no-benchmark",
            ]
        )
        capsys.readouterr()

        reproduce_dir = tmp_path / "cli_report_reproduce_dst"
        exit_code = main(
            [
                "analysis",
                "reproduce",
                "--output-dir",
                str(output_dir),
                "--reproduce-dir",
                str(reproduce_dir),
            ]
        )
        assert exit_code == 0
        assert "MATCH" in capsys.readouterr().out

    def test_reproduce_json_reports_matched_true(
        self, a_built_suite: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output_dir = tmp_path / "cli_report_reproduce_src_json"
        main(
            [
                "analysis",
                "run",
                "--build-id",
                a_built_suite,
                "--output-dir",
                str(output_dir),
                "--no-benchmark",
            ]
        )
        capsys.readouterr()

        reproduce_dir = tmp_path / "cli_report_reproduce_dst_json"
        exit_code = main(
            [
                "analysis",
                "reproduce",
                "--output-dir",
                str(output_dir),
                "--reproduce-dir",
                str(reproduce_dir),
                "--json",
            ]
        )
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["matched"] is True
        assert payload["mismatches"] == {}
