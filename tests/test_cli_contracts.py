"""Tests for the `credlens contracts ...` CLI commands.

Run against this repository's real contracts/raw and contracts/operational
directories and the real fixtures under tests/fixtures/contracts/ - no
mocking, since these commands are read-only and offline by design.
"""

from __future__ import annotations

import pytest

from credlens.cli import main


def test_contracts_list_exits_zero_and_lists_all_20(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["contracts", "list"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "CredLens data contracts" in captured.out
    assert "applications" in captured.out
    assert "uci_default_credit" in captured.out
    # title + underline + column header + 20 contract rows
    assert len(captured.out.strip().splitlines()) == 3 + 20


def test_contracts_show_known_contract(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["contracts", "show", "applications"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "applications" in captured.out
    assert "Primary key:    application_id" in captured.out
    assert "Business rules" in captured.out


def test_contracts_show_unknown_contract_fails(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["contracts", "show", "does_not_exist"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error:" in captured.out
    assert "Unknown contract" in captured.out


def test_contracts_no_subcommand_prints_usage_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["contracts"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "usage: credlens contracts" in captured.out


class TestContractsValidate:
    def test_audit_mode_never_fails_even_with_findings(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            [
                "contracts",
                "validate",
                "--contract",
                "applications",
                "--path",
                "tests/fixtures/contracts/invalid_domain",
                "--mode",
                "audit",
            ]
        )
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "DOMAIN_VIOLATION" in captured.out

    def test_strict_mode_fails_on_error_findings(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(
            [
                "contracts",
                "validate",
                "--contract",
                "applications",
                "--path",
                "tests/fixtures/contracts/invalid_domain",
                "--mode",
                "strict",
            ]
        )
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "DOMAIN_VIOLATION" in captured.out

    def test_strict_mode_passes_the_valid_fixture(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(
            [
                "contracts",
                "validate",
                "--contract",
                "applications",
                "--path",
                "tests/fixtures/contracts/valid_minimal_scenario",
                "--mode",
                "strict",
            ]
        )
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "No findings." in captured.out

    def test_invalid_mode_choice_is_rejected_by_argparse(self) -> None:
        with pytest.raises(SystemExit):
            main(
                [
                    "contracts",
                    "validate",
                    "--contract",
                    "applications",
                    "--path",
                    "tests/fixtures/contracts/valid_minimal_scenario",
                    "--mode",
                    "not_a_real_mode",
                ]
            )

    def test_unknown_path_reports_error_and_exits_1(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            [
                "contracts",
                "validate",
                "--contract",
                "applications",
                "--path",
                "does/not/exist.csv",
                "--mode",
                "audit",
            ]
        )
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "Error:" in captured.out
