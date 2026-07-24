"""Tests for the credlens CLI (foundation phase: help, version, doctor)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import credlens
from credlens.cli import DoctorCheck, main, run_doctor_checks


def test_help_exits_zero_and_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "usage" in captured.out.lower()
    assert "credlens" in captured.out.lower()


def test_no_command_prints_help_and_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "usage" in captured.out.lower()


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--version"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert credlens.__version__ in captured.out


def test_version_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["version"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.strip() == f"credlens {credlens.__version__}"


def test_doctor_subcommand_runs_and_reports_result(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["doctor"])
    captured = capsys.readouterr()

    assert exit_code in (0, 1)
    assert "CredLens doctor" in captured.out
    assert "Result:" in captured.out


def test_run_doctor_checks_covers_expected_checks() -> None:
    checks = run_doctor_checks()
    names = {check.name for check in checks}

    assert "python_version" in names
    assert "package_version" in names
    assert "config_file" in names
    assert "directory:config" in names
    assert "directory:docs" in names
    assert "data_sources" in names
    assert all(isinstance(check, DoctorCheck) for check in checks)


def test_run_doctor_checks_reports_data_sources_registry_status() -> None:
    # As of Phase 2, the real registry exists in this repository, so this
    # reflects genuine registered-source counts rather than an absence.
    checks = run_doctor_checks()
    data_sources_check = next(check for check in checks if check.name == "data_sources")

    assert data_sources_check.status == "INFO"
    assert "registered" in data_sources_check.detail


def test_run_doctor_checks_data_sources_not_configured_when_registry_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("credlens.cli.REGISTRY_PATH", Path("does/not/exist.yaml"))

    checks = run_doctor_checks()
    data_sources_check = next(check for check in checks if check.name == "data_sources")

    assert data_sources_check.status == "INFO"
    assert "future phase" in data_sources_check.detail


def test_run_doctor_checks_reports_failure_outside_repository_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run from a directory with no config/base.yaml and no project directories:
    doctor must report FAIL for those checks instead of raising or silently
    passing.
    """
    monkeypatch.chdir(tmp_path)

    checks = run_doctor_checks()
    by_name = {check.name: check for check in checks}

    assert by_name["config_file"].status == "FAIL"
    assert "not found" in by_name["config_file"].detail
    assert by_name["directory:config"].status == "FAIL"


def test_module_entrypoint_is_invocable() -> None:
    """`python -m credlens` is a documented way to run the CLI; exercise it for real."""
    result = subprocess.run(
        [sys.executable, "-m", "credlens", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert credlens.__version__ in result.stdout
